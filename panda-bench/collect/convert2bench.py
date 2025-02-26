import json
import csv
from datetime import datetime
from pathlib import Path

def filter_102_103_claims(ctnf_data):
    filtered_claims = []
    has_valid_rejection = False
    
    for claim in ctnf_data["claims"]:
        valid_reasons = []
        for reason in claim.get("reasons", []):
            if reason.get("sectionCode") in [102, 103]:
                valid_reasons.append(reason)
                has_valid_rejection = True
        
        claim["reasons"] = valid_reasons
        if not valid_reasons:
            claim["isReject"] = False
        filtered_claims.append(claim)
    
    ctnf_data["claims"] = filtered_claims
    return ctnf_data, has_valid_rejection

def create_benchmark_data():
    # Setup directories
    output_dir = Path("./data/benchmark")
    record_dir = Path("./data/record")
    ctnf_dir = Path("./data/parsed_CTNF")
    validation_dir = Path("./data/validation")
    error_dir = Path("./data/error_report")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    error_dir.mkdir(parents=True, exist_ok=True)

    # Setup error logging for benchmark
    current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    error_log_path = error_dir / f"error_bench_{current_time}.csv"

    with open(error_log_path, 'w', newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["rec_num", "app_num", "error_code", "error_message"])
        writer.writeheader()

    # Read validation results
    validation_result_path = validation_dir / "validation_result.csv"
    valid_records = []
    
    with open(validation_result_path, 'r', newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["valid_b"].lower() == "true":
                valid_records.append({
                    "rec_num": int(row["rec_num"]),
                    "app_num": row["app_num"]
                })

    # Sort by rec_num
    valid_records.sort(key=lambda x: x["rec_num"])
    
    successful_count = 0
    for record in valid_records:
        rec_num = record["rec_num"]
        app_num = record["app_num"]
        
        try:
            # Find corresponding files
            record_file = next(record_dir.glob(f"rec_r{rec_num:05d}_{app_num}.json"))
            ctnf_files = list(ctnf_dir.glob(f"pC_*_{app_num}.json"))

            if not ctnf_files or len(ctnf_files) > 1:
                print(f"Warning: Invalid CTNF files for {app_num}")
                continue

            ctnf_file = ctnf_files[0]

            # Read files
            with open(record_file, 'r') as f:
                record_data = json.load(f)

            with open(ctnf_file, 'r') as f:
                ctnf_data = json.load(f)

            # 102/103 필터링
            filtered_ctnf, has_valid_rejection = filter_102_103_claims(ctnf_data)
            
            if not has_valid_rejection:
                with open(error_log_path, 'a', newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=["rec_num", "app_num", "error_code", "error_message"])
                    writer.writerow({
                        "rec_num": rec_num,
                        "app_num": app_num,
                        "error_code": 300,
                        "error_message": "No 102/103 rejections found"
                    })
                print(f"❌ No 102/103 rejections found for application {app_num}")
                continue

            # Create benchmark data
            benchmark_data = {
                "bench_id": successful_count + 1,
                "applicationNumber": int(app_num),
                "abstract": record_data["abstract"],
                "claims": record_data["initialClaims"],
                "gold_ctnf": filtered_ctnf,
                "patentsCitedByExaminer": record_data.get("patentsCitedByExaminer", [])
            }

            # Save benchmark file
            successful_count += 1
            formatted_count = f"{successful_count:05d}"
            output_file = output_dir / f"bench_b{formatted_count}_{app_num}.json"

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(benchmark_data, f, indent=4, ensure_ascii=False)

            print(f"✅ Created benchmark data for application {app_num} (benchmark #{formatted_count})")
            
            with open(error_log_path, 'a', newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["rec_num", "app_num", "error_code", "error_message"])
                writer.writerow({
                    "rec_num": rec_num,
                    "app_num": app_num,
                    "error_code": -1,
                    "error_message": ""
                })

        except Exception as e:
            print(f"Error processing application {app_num}: {e}")
            with open(error_log_path, 'a', newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["rec_num", "app_num", "error_code", "error_message"])
                writer.writerow({
                    "rec_num": rec_num,
                    "app_num": app_num,
                    "error_code": 400,
                    "error_message": str(e)
                })

if __name__ == "__main__":
    create_benchmark_data()
