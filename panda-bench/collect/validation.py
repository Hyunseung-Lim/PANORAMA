import os
import json
import re
import csv
import openai
import time
from pathlib import Path
from datetime import datetime
from openai import OpenAI

client = OpenAI(api_key="")

def get_cited_patents(claims):
    cited_patents = set()
    for claim in claims:
        for reason in claim.get("reasons", []):
            cited_patents.update(reason.get("citedPatents", []))
    return {re.sub(r'\D', '', patent) for patent in cited_patents}

def get_examiner_patents(patents_cited):
    return {re.sub(r'\D', '', patent.get("referenceIdentifier", "")) 
            for patent in patents_cited}

def filter_cancelled_claims(initial_claims):
    # 취소된 클레임 번호 추출
    cancelled_numbers = []
    filtered_claims = []
    
    for claim in initial_claims:
        # 정규식 패턴 수정 - 클레임 번호 추출을 더 정확하게
        match = re.search(r'^"?(\d+)\s*\.\s*\(?[Cc]ancelled\)?', claim.strip())
        if match:
            cancelled_numbers.append(int(match.group(1)))
        else:
            # cancelled가 포함되지 않은 경우에만 추가
            if not re.search(r'\([Cc]ancelled\)', claim):
                filtered_claims.append(claim)
    
    return filtered_claims, cancelled_numbers

def validate_record_ctnf(record_data, ctnf_data, app_num, rec_num):
    error_code = -1
    error_message = []
    
    # 1. Claim 수 비교
    ctnf_claims_count = len(ctnf_data.get("claims", []))
    record_claims_count = len(record_data.get("initialClaims", []))
    
    if ctnf_claims_count != record_claims_count:
        error_code = 100
        error_message.append(f"Claims count: CTNF={ctnf_claims_count}, Record={record_claims_count}")
    
    # 2. 인용 특허 비교
    ctnf_patents = get_cited_patents(ctnf_data.get("claims", []))
    record_patents = get_examiner_patents(record_data.get("patentsCitedByExaminer", []))
    
    if ctnf_patents != record_patents:
        only_in_ctnf = ctnf_patents - record_patents
        if only_in_ctnf:
            error_code = 110 if error_code == -1 else error_code
            error_message.append(f"Patents only in CTNF: {', '.join(only_in_ctnf)}")
    
    if error_code != -1:
        return {
            "rec_num": rec_num,
            "app_num": app_num,
            "error_code": error_code,
            "error_message": "; ".join(error_message) if error_message else ""
        }
    return None

def filter_ctnf_claims(ctnf_data, cancelled_numbers):
    # 취소된 클레임 번호에 해당하는 CTNF claim 제외
    filtered_claims = []
    
    for claim in ctnf_data["claims"]:
        if claim["claimNumber"] not in cancelled_numbers:
            filtered_claims.append(claim)
    
    ctnf_data["claims"] = filtered_claims
    return ctnf_data

def basic_validation(record_data, ctnf_data, rec_num):
    app_num = record_data.get("applicationNumber", "unknown")
    
    # 1. Cancelled claim 필터링
    filtered_claims, cancelled_numbers = filter_cancelled_claims(record_data["initialClaims"])
    record_data["initialClaims"] = filtered_claims
    
    # 2. CTNF claim 필터링 - cancelled claims 제외
    ctnf_data_filtered = filter_ctnf_claims(ctnf_data, cancelled_numbers)
    
    # 데이터 검증
    validation_error = validate_record_ctnf(record_data, ctnf_data_filtered, app_num, rec_num)
    if validation_error:
        return None, validation_error
    
    return {
        "record_data": record_data,
        "ctnf_data": ctnf_data_filtered
    }, None

def gpt_validation(validated_data, error_log_path, rec_num):
    app_num = validated_data["record_data"].get("applicationNumber", "unknown")
    
    # GPT 검증
    if not validate_with_gpt(validated_data["record_data"], validated_data["ctnf_data"], app_num, rec_num, error_log_path):
        return None
    
    # 성공 시 로그 기록
    with open(error_log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["rec_num", "app_num", "error_code", "error_message"])
        writer.writerow({
            "rec_num": rec_num,
            "app_num": app_num,
            "error_code": -1,
            "error_message": ""
        })
    
    return validated_data

def validate_with_gpt(record_data, ctnf_data, app_num, rec_num, error_log_path):
    try:
        ctnf_body_text = record_data.get("CTNFBodyText", "")
        parsed_claims = ctnf_data.get("claims", [])

        claims_data = []
        for claim in parsed_claims:
            claim_number = claim.get("claimNumber", "unknown")
            parsed_claim = {
                "claimNumber": claim_number,
                "sectionCode": [reason["sectionCode"] for reason in claim.get("reasons", [])],
                "citedPatents": [patent for reason in claim.get("reasons", []) for patent in reason.get("citedPatents", [])]
            }
            claims_data.append(parsed_claim)

        body = {
            "model": "gpt-4o",
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {
                    "role": "user",
                    "content": f"""
                    You are an expert of patent. Compare the parsed CTNF data with the CTNFBodyText for all claims.
                    Instructions:
                        1. For each claim, verify:
                        - The section code matches **exactly**.
                        - The cited patents match **exactly**.

                        2. **Only mark a field as false if you are certain it does not match.** 
                        - If there is any ambiguity or you are not entirely certain, mark it as true.

                        3. In the "details" field, provide **thorough** explanations for why there is a mismatch (if any).  
                        - If there is no mismatch, you may leave "details" empty or omit it.

                        4. Use the following JSON array of objects format **exactly**, with no additional text or formatting:
                        [{{"claimNumber": <claimNumber>, "sectionCodeMatch": (true/false), "citedPatentsMatch": (true/false), "details": "<thorough explanation if mismatched>"}}]

                        5. **Do not** include any extra commentary, markdown, or text outside of this JSON array.

                    CTNFBodyText:
                    {ctnf_body_text}

                    Parsed CTNF for all claims:
                    {claims_data}
                    """
                }
            ]
        }
        response = client.chat.completions.create(**body)
        results = json.loads(response.choices[0].message.content.replace("\n", "").replace("```json", "").replace("```", ""))
        
        for result in results:
            if not result.get("sectionCodeMatch", False) or not result.get("citedPatentsMatch", False):
                with open(error_log_path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=["rec_num", "app_num", "error_code", "error_message"])
                    writer.writerow({
                        "rec_num": rec_num,
                        "app_num": app_num,
                        "error_code": 210,
                        "error_message": f"Invalid claim found: {results}"
                    })
                return False
        return True

    except Exception as e:
        with open(error_log_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["rec_num", "app_num", "error_code", "error_message"])
            writer.writerow({
                "rec_num": rec_num,
                "app_num": app_num,
                "error_code": 200,
                "error_message": str(e)
            })
        return False

def main(run_basic=True, run_gpt=True):
    # Setup directories
    record_dir = Path("./data/record")
    ctnf_dir = Path("./data/parsed_CTNF")
    error_dir = Path("./data/error_report")
    validation_dir = Path("./data/validation")
    error_dir.mkdir(parents=True, exist_ok=True)
    validation_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize validation results dictionary
    validation_results = {}
    validated_data_dict = {}
    current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    if run_basic:
        print("Starting basic validation...")
        error_log_path = error_dir / f"error_valid_basic_{current_time}.csv"
        
        # 파일들을 rec_num 순서대로 정렬하기 위해 리스트로 수집
        record_files = []
        for record_file in record_dir.glob("rec_r*_*.json"):
            try:
                file_parts = record_file.stem.split('_')
                rec_num = int(re.sub(r'\D', '', file_parts[1]))
                app_num = file_parts[-1]
                record_files.append((rec_num, app_num, record_file))
                
                # 여기서 먼저 validation_results 초기화
                validation_results[app_num] = {
                    "rec_num": rec_num,
                    "app_num": app_num,
                    "valid_b": False,
                    "valid_g": False
                }
            except Exception as e:
                print(f"Error parsing filename {record_file}: {e}")
                continue

        # rec_num 기준으로 정렬
        record_files.sort(key=lambda x: x[0])
        print(f"Total {len(record_files)} record files found and sorted")

        with open(error_log_path, 'w', newline="", encoding="utf-8") as error_file:
            writer = csv.DictWriter(error_file, fieldnames=["rec_num", "app_num", "error_code", "error_message"])
            writer.writeheader()

            for rec_num, app_num, record_file in record_files:
                try:
                    # validation_results는 이미 위에서 초기화됨
                    
                    # CTNF 파일 체크
                    ctnf_files = list(ctnf_dir.glob(f"pC_r{rec_num:05d}_*.json"))
                    if not ctnf_files or len(ctnf_files) > 1:
                        writer.writerow({
                            "rec_num": rec_num,
                            "app_num": app_num,
                            "error_code": 150,
                            "error_message": "No matching CTNF file"
                        })
                        continue

                    ctnf_file = ctnf_files[0]

                    try:
                        with open(record_file, 'r') as f:
                            record_data = json.load(f)

                        with open(ctnf_file, 'r') as f:
                            ctnf_data = json.load(f)
                    except json.JSONDecodeError as e:
                        print(f"❌ Invalid JSON format in files for rec_{rec_num} (app_{app_num})")
                        writer.writerow({
                            "rec_num": rec_num,
                            "app_num": app_num,
                            "error_code": 160,
                            "error_message": f"Invalid JSON format: {str(e)}"
                        })
                        continue

                    if not isinstance(ctnf_data, dict) or "claims" not in ctnf_data:
                        print(f"❌ Invalid CTNF data structure for rec_{rec_num} (app_{app_num})")
                        writer.writerow({
                            "rec_num": rec_num,
                            "app_num": app_num,
                            "error_code": 170,
                            "error_message": "Invalid CTNF data structure"
                        })
                        continue

                    print(f"Processing basic validation for application {app_num} (rec_{rec_num})...")
                    validated_data, validation_error = basic_validation(record_data, ctnf_data, rec_num)
                    
                    if validation_error:
                        writer.writerow(validation_error)
                        print(f"❌ Basic validation failed for application {app_num}")
                    else:
                        writer.writerow({
                            "rec_num": rec_num,
                            "app_num": app_num,
                            "error_code": -1,
                            "error_message": ""
                        })
                        print(f"✅ Basic validation successful for application {app_num}")
                        validated_data_dict[app_num] = validated_data
                        validation_results[app_num]["valid_b"] = True

                except Exception as e:
                    print(f"Error processing application {app_num}: {e}")
                    writer.writerow({
                        "rec_num": rec_num,
                        "app_num": app_num,
                        "error_code": 400,
                        "error_message": str(e)
                    })
    else:
        # Load existing validation results if skipping basic validation
        validation_result_path = validation_dir / "validation_result.csv"
        if validation_result_path.exists():
            with open(validation_result_path, 'r', newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    app_num = row["app_num"]
                    validation_results[app_num] = {
                        "rec_num": int(row["rec_num"]),
                        "app_num": app_num,
                        "valid_b": row["valid_b"].lower() == "true",
                        "valid_g": row["valid_g"].lower() == "true"
                    }

    if run_gpt:
        # GPT validation 수행
        print("\nStarting GPT validation...")
        gpt_error_log_path = error_dir / f"error_valid_gpt_{current_time}.csv"
        
        with open(gpt_error_log_path, 'w', newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["rec_num", "app_num", "error_code", "error_message"])
            writer.writeheader()

        # validated_data_dict를 rec_num 순서대로 처리
        sorted_validated_data = sorted(validated_data_dict.items(), 
                                     key=lambda x: validation_results[x[0]]["rec_num"])
        
        for app_num, data in sorted_validated_data:
            try:
                rec_num = validation_results[app_num]["rec_num"]
                print(f"Processing GPT validation for application {app_num} (rec_{rec_num})...")
                gpt_validated = gpt_validation(data, gpt_error_log_path, rec_num)
                
                if gpt_validated:
                    print(f"✅ GPT validation successful for application {app_num}")
                    validation_results[app_num]["valid_g"] = True
                else:
                    print(f"❌ GPT validation failed for application {app_num}")

            except Exception as e:
                print(f"Error in GPT validation for application {app_num}: {e}")

    # Write validation results to CSV
    validation_result_path = validation_dir / "validation_result.csv"
    with open(validation_result_path, 'w', newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["rec_num", "app_num", "valid_b", "valid_g"])
        writer.writeheader()
        sorted_results = sorted(validation_results.values(), key=lambda x: x["rec_num"])
        for result in sorted_results:
            writer.writerow(result)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Run validation with specified options')
    parser.add_argument('--basic', action='store_true', help='Run basic validation')
    parser.add_argument('--gpt', action='store_true', help='Run GPT validation')
    args = parser.parse_args()

    # 아무 옵션도 지정되지 않았다면 둘 다 실행
    if not args.basic and not args.gpt:
        args.basic = True
        args.gpt = False

    main(run_basic=args.basic, run_gpt=args.gpt)