import os
import json
import requests
from patent_client import PublishedApplication, Patent
import xml.etree.ElementTree as ET
from datetime import datetime
from utils import extract_claims, validate_claims
import time
import re

USPTO_API_KEY = ""

# 입력값 예시
from_date = "2018-01-23T00:00:00"  # ISO 형식
to_date = "2021-01-23T00:00:00"    # ISO 형식

# 결과 저장 경로 설정
output_dir = "./data/record"
spec_text_dir = "./data/spec_app/text"
spec_image_dir = "./data/spec_app/image"
cited_spec_text_dir = "./data/spec_cited/text"
cited_spec_image_dir = "./data/spec_cited/image"

# 필요한 디렉토리들을 미리 생성
os.makedirs(output_dir, exist_ok=True)
os.makedirs(spec_text_dir, exist_ok=True)
os.makedirs(spec_image_dir, exist_ok=True)
os.makedirs(cited_spec_text_dir, exist_ok=True)
os.makedirs(cited_spec_image_dir, exist_ok=True)

# 1. OA Text Retrieval API를 통해 'CTNF' 문서 데이터 수집
def fetch_ctnf_documents(from_date, to_date, start_Num):
    print("Fetching CTNF documents...")
    url = "https://developer.uspto.gov/ds-api/oa_actions/v1/records"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }
    criteria = f"legacyDocumentCodeIdentifier:CTNF AND sections.grantDate:[{from_date} TO {to_date}]"
    data = {
        "criteria": criteria,
        "start": start_Num,
        "rows": 100
    }
    response = requests.post(url, headers=headers, data=data)
    data = response.json()
    
    # 필요한 필드 추출
    ctnf_data = [
        {
            "title": record["inventionTitle"][0],
            "applicationNumber": record["patentApplicationNumber"][0],
            "grantDate": record["sections.grantDate"],
            "techCenter": record["techCenter"][0],
            "CTNFBodyText": record["bodyText"][0].split("Any inquiry concerning this communication")[0],
            "obsoleteDocumentIdentifier": record["obsoleteDocumentIdentifier"][0]
        }
        for record in data['response']["docs"]
    ]
    print(f"Retrieved {len(ctnf_data)} CTNF documents.")
    return ctnf_data


# 3. Citation의 referenceId로부터 spec과 claim, abstract, drawing 정보 수집
def fetch_grant_document(identifier):
    # 정규식 패턴 정의 (publication number는 숫자 11자리 형식, application number는 숫자 7~8자리 형식)
    trimed_idendtifier = re.sub(r'[a-zA-Z]', '', identifier)

    publication_pattern = re.compile(r'^\d{11}$')
    application_pattern = re.compile(r'^\d{7,8}$')

    try:
        # publication number로 판단되면 PublishedApplication 사용
        if publication_pattern.match(trimed_idendtifier):
            print(f"Fetching grant document for publication number {trimed_idendtifier}...")
            patent = PublishedApplication.objects.get(trimed_idendtifier)
        # application number로 판단되면 Patent 사용
        elif application_pattern.match(trimed_idendtifier):
            print(f"Fetching grant document for application number {trimed_idendtifier}...")
            patent = Patent.objects.get(trimed_idendtifier)
        else:
            raise ValueError(f"Invalid identifier format. Please provide a valid application or publication number. input: {identifier}")
        
        application_number = patent.appl_id
        # 특허의 description 및 claims 텍스트 추출
        description = patent.description
        abstract = patent.abstract
        drawing = get_document_content(get_application_documents(application_number), "DRW", target_document_identifier=None, mimeTypeIdentifier="PDF")
        
        claims = [claim.text for claim in patent.claims]

        print(f"Spec, Abstract and claims retrieved for {trimed_idendtifier}.")
        return {"spec": description, "abstract": abstract, "claims": claims, "drawing": drawing}
    
    except Exception as e:
        print(f"Failed to fetch data for {trimed_idendtifier}: {e}")
        return {"spec": "", "abstract": "", "claims": [], "drawing": ""}

# 4. Enriched Cited Reference Metadata API를 통해 citation list 수집
def extract_citations(CTNFtext):
    # 콤마를 제거하고 패턴 매칭
    CTNFtext = re.sub(r'(\d),(\d)', r'\1\2', CTNFtext)
    
    unique_citations = set()
    
    # xxxx/xxxxxxx 형식을 먼저 찾아서 11자리 숫자로 변환
    slash_pattern = r'(?<!\d)(\d{4}/\d{7})(?!\d)'
    slash_matches = re.findall(slash_pattern, CTNFtext)
    
    # slash_matches에서 찾은 패턴을 CTNFtext에서 제거
    for match in slash_matches:
        CTNFtext = CTNFtext.replace(match, '')
        unique_citations.add(match.replace('/', ''))
    
    # 11자리 숫자 패턴
    unique_citations.update(re.findall(r'(?<!\d)\d{11}(?!\d)', CTNFtext))
    
    # 7-8자리 숫자 패턴 (앞의 패턴들과 겹치지 않는 것만)
    unique_citations.update(re.findall(r'(?<!\d)\d{7,8}(?!\d)', CTNFtext))
    
    print(f"Found {len(unique_citations)} unique citations in the CTNF text.: {unique_citations}")

    patents_cited = []
    cleaned_citations = {re.sub(r'[^\d]', '', citation) for citation in unique_citations}
    
    for id in cleaned_citations:
        cited_patent_info = fetch_grant_document(id)
        if cited_patent_info["claims"] == []:
            print(f"Patent {id} cited by examiner has no claims.")
            raise ValueError(f"Patent {id} cited by examiner has no claims")
            
        patents_cited.append({
            "referenceIdentifier": id,
            "spec": cited_patent_info["spec"],
            "abstract": cited_patent_info["abstract"],
            "claims": cited_patent_info["claims"],
            "drawing": cited_patent_info["drawing"]
        })
    
    return patents_cited

# 5. patent_client.odp에서 patentApplicationNumber로 CLM 문서 조회 및 XML 다운로드
import requests
import xml.etree.ElementTree as ET

def fetch_rejected_claims(document_identifier, application_number, documents):
    # 입력 document_identifier에 해당하는 객체 찾기
    print(f"{application_number}: Fetching rejected claims for document {document_identifier}...")
    target_index = next((i for i, doc in enumerate(documents) if doc["documentIdentifier"] == document_identifier), None)
    if target_index is None:
        print("Error: Document identifier not found.")
        return []

    # 대상 document_identifier 이전의 가장 최근 CLM 문서 찾기
    recent_clm_doc = None
    clm_docs_on_latest_date = []
    latest_date = None
    
    for doc in documents[:target_index][::-1]:  # 최신순으로 역순 탐색
        if doc["documentCode"] == "CLM":
            if latest_date is None:
                latest_date = doc["officialDate"]
                clm_docs_on_latest_date.append(doc)
            elif doc["officialDate"] == latest_date:
                clm_docs_on_latest_date.append(doc)
                
    if len(clm_docs_on_latest_date) > 1:
        print(f"Error: Multiple CLM documents found on {latest_date}")
        raise ValueError(f"Multiple CLM documents found on {latest_date}")
    elif len(clm_docs_on_latest_date) == 1:
        recent_clm_doc = clm_docs_on_latest_date[0]

    # CLM 파일이 없다면 None 반환
    if not recent_clm_doc:
        print("Error: CLM document not found before the target document.")
        raise ValueError("CLM document not found before the target document.")

    # XML 파일의 downloadURL 찾기
    xml_download_url = next(
        (option["downloadUrl"] for option in recent_clm_doc["downloadOptionBag"] if option["mimeTypeIdentifier"] == "XML"),
        None
    )
    if not xml_download_url:
        print("Error: XML download URL not found.")
        raise ValueError("XML download URL not found.")

    # XML 파일 다운로드
    headers = {"X-API-KEY": USPTO_API_KEY}
    xml_response = requests.get(xml_download_url, headers=headers)
    xml_response.raise_for_status()
    content = xml_response.content

    # XML 시작 부분 찾기 및 null byte 제거
    start_idx = content.find(b'<?xml')
    if start_idx == -1:
        print("Error: XML content not found in the file.")
        raise ValueError("XML content not found in the file.")

    xml_content = content[start_idx:].replace(b'\x00', b'').decode('utf-8', errors='ignore')

    # XML 파싱하여 거절된 청구항 추출
    try:
        rejected_claims = extract_claims(xml_content)
    except ET.ParseError as e:
        print("XML parsing error:", e)
        raise ValueError(f"Failed to parse XML: {e}")

    if not validate_claims(rejected_claims):
        print("Error: Invalid claim format.")
        raise ValueError("Invalid claim format.")
    
    if not rejected_claims:
        print("Error: No rejected claims found.")
        raise ValueError("No rejected claims found.")
    
    print(f"Rejected claims retrieved for application {application_number}.")
    return rejected_claims


def is_first_clm_ctnf(target_ctnf_document_id, sorted_documents):
    first_ctnf_found = None
    for doc in sorted_documents:
        if doc["documentCode"] == "CTNF":
            first_ctnf_found = doc
            break

    is_first = first_ctnf_found is not None and first_ctnf_found["documentIdentifier"] == target_ctnf_document_id
    return is_first


def get_document_content(app_documents, document_code, target_document_identifier=None, mimeTypeIdentifier="XML"):
    target_index = len(app_documents) if target_document_identifier is None else next((i for i, doc in enumerate(app_documents) if doc["documentIdentifier"] == target_document_identifier), None)
    if target_index is None:
        print("Error: Document identifier not found.")
        return []

    if document_code == "NOA":
        # 대상 document_identifier 이전의 NOA 문서들을 순서대로 확인
        # (이미 app_documents가 officialDate로 정렬되어 있으므로 가장 오래된 것부터 확인됨)
        for doc in app_documents[:target_index]:
            if doc["documentCode"] == "NOA":
                # XML 다운로드 URL 찾기
                download_url = next(
                    (option["downloadUrl"] for option in doc.get("downloadOptionBag", []) if option["mimeTypeIdentifier"] == "XML"),
                    None
                )
                if download_url:
                    # XML 파일이 있는 NOA 문서를 찾으면 해당 문서의 내용을 반환
                    headers = {"X-API-KEY": USPTO_API_KEY}
                    response = requests.get(download_url, headers=headers)
                    response.raise_for_status()
                    print(f"Retrieved NOA document.")
                    return response.content
        
        # XML이 있는 NOA 문서를 찾지 못한 경우
        print(f"No NOA document with XML format found.")
        return ""

    # 대상 document_identifier 이전의 가장 최근 document_code 문서 찾기
    recent_doc = None
    for doc in app_documents[:target_index][::-1]:  # 최신순으로 역순 탐색
        if doc["documentCode"].split(".")[0] == document_code:
            recent_doc = doc
            break

    download_url = next(
        (option["downloadUrl"] for option in recent_doc.get("downloadOptionBag", []) if option["mimeTypeIdentifier"] == mimeTypeIdentifier),
        None
    )

    if not download_url:
        if document_code == "DRW":
            print(f"No drawing found for {target_document_identifier}.")
        else:
            print(f"Error: {mimeTypeIdentifier} download URL not found.")
        return ""

    # 콘텐츠를 다운로드하여 content 변수에 저장 (여기서는 파일을 열지 않고 다운로드 URL에서 가져오는 방식 사용)
    headers = {"X-API-KEY": USPTO_API_KEY}
    response = requests.get(download_url, headers=headers)
    response.raise_for_status()
    content = response.content
    print(f"Content retrieved.")

    return content

def parse_xml(content):
    # XML 시작 부분 찾기 및 null byte 제거
    start_idx = content.find(b'<?xml')
    if start_idx == -1:
        print(f"Error: xml content not found in the file.")
        return ""
    content = content[start_idx:].replace(b'\x00', b'').decode('utf-8', errors='ignore')

    # XML 파싱
    root = ET.fromstring(content)

    # XML의 모든 텍스트를 추출하는 함수
    def extract_all_text(element):
        text_content = []
        if element.text:
            text_content.append(element.text.strip())  # 태그 안의 텍스트 추가
        for subelement in element:
            text_content.extend(extract_all_text(subelement))  # 하위 요소에 대해 재귀적으로 텍스트 추가
        if element.tail:
            text_content.append(element.tail.strip())  # 태그 뒤의 텍스트 추가
        return text_content  

    # 텍스트 추출 및 결합
    document_text = ' '.join(extract_all_text(root)).strip()
    
    return document_text

def get_application_documents(app_number):
    """
    특허 출원 번호로 문서 목록을 가져오고 날짜순으로 정렬하는 함수
    
    Args:
        app_number (str): 특허 출원 번호
    
    Returns:
        list: officialDate 기준으로 정렬된 문서 목록
    """
    base_url = f"https://beta-api.uspto.gov/api/v1/patent/applications/{app_number}/documents"
    headers = {
        "X-API-KEY": USPTO_API_KEY
    }

    # API 호출하여 JSON 데이터를 가져오기
    response = requests.get(base_url, headers=headers)
    response.raise_for_status()
    documents = response.json()['documentBag']
    
    # officialDate를 기준으로 정렬 (오래된 순)
    return sorted(documents, key=lambda x: x["officialDate"])

def is_finally_rejected(sorted_documents):
    final_docs = [doc for doc in sorted_documents if doc["documentCode"] in ["NOA", "CTFR"]]
    
    if not final_docs:
        return False
        
    latest_doc = final_docs[-1]
    return latest_doc["documentCode"] == "CTFR"

def has_abst_or_spec_between_ctnf_and_noa(sorted_documents, ctnf_document_identifier, noa_document_identifier):
    ctnf_index = next((i for i, doc in enumerate(sorted_documents) 
                      if doc["documentIdentifier"] == ctnf_document_identifier), None)
    noa_index = next((i for i, doc in enumerate(sorted_documents) 
                     if doc["documentIdentifier"] == noa_document_identifier), None)
    
    if ctnf_index is None or noa_index is None:
        return False

    between_docs = sorted_documents[min(ctnf_index, noa_index):max(ctnf_index, noa_index)]

    return any(doc["documentIdentifier"] in ['ABST', 'SPEC'] for doc in between_docs)

# 전체 실행
def main(from_date, to_date):
    start_Num = 0
    
    # successful_record_count 초기화 로직 수정
    try:
        existing_files = os.listdir(output_dir)
        # rec_rXXXXX_ 형식의 파일들에서 숫자 추출
        record_numbers = []
        for file in existing_files:
            if file.startswith('rec_r'):
                try:
                    # 'r' 다음의 숫자 추출 (leading zeros 무시)
                    number = int(file.split('_')[1].lstrip('r0'))
                    record_numbers.append(number)
                except (ValueError, IndexError):
                    continue
        
        # 추출된 숫자가 있으면 최대값, 없으면 0
        successful_record_count = max(record_numbers) if record_numbers else 0
        print(f"Starting with record number: {successful_record_count + 1}")
    except Exception as e:
        print(f"Error initializing record count: {e}. Starting from 0")
        successful_record_count = 0
    
    final_data = []    
    # 에러 로그 파일명 생성 (한 번만)
    error_log_path = f"./data/error_report/error_rec_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"
    
    # CSV 파일 헤더 생성 (한 번만)
    if not os.path.exists(error_log_path):
        with open(error_log_path, "w") as f:
            f.write("pre_num,rec_num,app_num,error_code,error_message,timestamp\n")
    
    while True:
        try:
            print(f"\n=== Processing batch starting from {start_Num} ===")
            ctnf_data = fetch_ctnf_documents(from_date, to_date, start_Num)
            
            # 더 이상 데이터가 없으면 종료
            if not ctnf_data:
                print(f"No more data available after start_Num {start_Num}. Ending process.")
                break

            for idx, data in enumerate(ctnf_data):
                record_number = start_Num + idx
                app_number = data["applicationNumber"]
                error_message = ""
                error_code = -1
                formatted_record_number = f"{successful_record_count + 1:05d}"

                # 이미 존재하는 파일 확인
                existing_files = os.listdir(output_dir)
                if any(f"rec_r" in f and f"_{app_number}.json" in f for f in existing_files):
                    print(f"❌ {app_number} already in data")
                    error_message = f"{app_number} already in data"
                    error_code = 70
                    log_error()
                    continue

                # 에러 로그 기록 함수
                def log_error():
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    rec_num = int(formatted_record_number) if error_code == -1 else -1
                    with open(error_log_path, "a") as f:
                        f.write(f"{record_number},{rec_num},{app_number},{error_code},\"{error_message}\",{timestamp}\n")

                sorted_documents = get_application_documents(app_number)

                start_time = time.time()

                # 해당 문서가 해당 특허의 첫 번째 CTNF가 아니면 pass
                if not is_first_clm_ctnf(data["obsoleteDocumentIdentifier"], sorted_documents):
                    error_message = f"Non-first CTNF: {data['obsoleteDocumentIdentifier']}"
                    error_code = 10
                    log_error()
                    continue

                # 최종적으로 거절된 경우(CTFR 받은 경우) pass
                if is_finally_rejected(sorted_documents):
                    print(f"❌ Got CTFR: {data['obsoleteDocumentIdentifier']}")
                    error_message = f"Got CTFR: {data['obsoleteDocumentIdentifier']}"
                    error_code = 20
                    log_error()
                    continue

                # NOA 파일 존재 여부 확인
                noa_document_identifier = next((doc["documentIdentifier"] for doc in sorted_documents if doc["documentCode"] == "NOA"), None)
                if noa_document_identifier is None:
                    print(f"❌ NOA document not found")
                    error_message = "NOA document not found"
                    error_code = 30
                    log_error()
                    continue

                # NOA XML 파일 가져오기 시도
                try:
                    noa_body_text = parse_xml(get_document_content(sorted_documents, "NOA"))
                    if not noa_body_text:  # XML 파일이 없는 경우
                        print(f"❌ NOA document exists but XML format not found")
                        error_message = "NOA document exists but XML format not found"
                        error_code = 31
                        log_error()
                        continue
                except Exception as e:
                    print(f"❌ Failed to parse NOA XML: {e}")
                    error_message = f"Failed to parse NOA XML: {e}"
                    error_code = 32
                    log_error()
                    continue

                # CTNF와 NOA 사이에 ABST나 SPEC이 있는 경우 pass
                if has_abst_or_spec_between_ctnf_and_noa(sorted_documents, data["obsoleteDocumentIdentifier"], noa_document_identifier):
                    print(f"❌ ABST or SPEC is modified between CTNF and NOA")
                    error_message = f"ABST or SPEC is modified between CTNF and NOA"
                    error_code = 40
                    log_error()
                    continue

                # 참조 특허 가져오기
                try:
                    patents_cited = extract_citations(data["CTNFBodyText"])
                except ValueError as e:
                    if "cited by examiner has no claims" in str(e):
                        print(f"❌ Cited patent has no claims: {e}")
                        error_message = f"Cited patent has no claims: {e}"
                        error_code = 61  # 인용특허의 청구항이 없는 경우의 새로운 에러 코드
                    else:
                        print(f"❌ Failed to process cited patents: {e}")
                        error_message = f"Failed to process cited patents: {e}"
                        error_code = 60  # 기타 인용특허 관련 에러
                    log_error()
                    continue

                # metadata 가져오기
                metadata_url = f"https://beta-api.uspto.gov/api/v1/patent/applications/{app_number}/meta-data"
                metadata_response = requests.get(metadata_url, headers={"X-API-KEY": USPTO_API_KEY})
                metadata_response.raise_for_status()
                metadata = {k: v for k, v in metadata_response.json()["patentFileWrapperDataBag"][0]["applicationMetaData"].items() if k != "inventorBag"}
                print(f"Metadata retrieved for application {app_number}.")
                
                # spec 가져오기
                try:
                    print(f"Fetching specification for application {app_number}...")
                    desc = parse_xml(get_document_content(sorted_documents, "SPEC", target_document_identifier=data["obsoleteDocumentIdentifier"]))
                except Exception as e:
                    print(f"❌ Failed to fetch specification for application {app_number}: {e}")
                    error_message = f"Failed to fetch or parse specification: {e}"
                    error_code = 51
                    log_error()
                    continue

                # abstract 가져오기
                try:
                    print(f"Fetching abstract for application {app_number}...")
                    abstract = "ABSTRACT" + parse_xml(get_document_content(sorted_documents, "ABST", target_document_identifier=data["obsoleteDocumentIdentifier"])).split("ABSTRACT")[-1]
                except Exception as e:
                    print(f"❌ Failed to fetch abstract for application {app_number}: {e}")
                    error_message = f"Failed to fetch or parse abstract: {e}"
                    error_code = 52
                    log_error()
                    continue

                # drawing 가져오기
                try:
                    print(f"Fetching drawing for application {app_number}...")
                    drw = get_document_content(sorted_documents, "DRW", target_document_identifier=data["obsoleteDocumentIdentifier"], mimeTypeIdentifier="PDF")
                except Exception as e:
                    print(f"❌ Failed to fetch drawing for application {app_number}: {e}")
                    error_message = f"Failed to fetch or parse drawing although it exists: {e}"
                    error_code = 53
                    log_error()
                    continue
  
                # 거절된 청구항 가져오기
                try:
                    initial_claims = fetch_rejected_claims(data["obsoleteDocumentIdentifier"], app_number, sorted_documents)
                except Exception as e:
                    print(f"❌ Failed to fetch initial claims for application {app_number}: {e}")
                    error_message = f"Failed to fetch or parse initial claims: {e}"
                    error_code = 54
                    log_error()
                    continue

                if initial_claims == []:
                    print(f"❌ Initial claims for application {app_number} is Empty")
                    error_message = "Initial claims is Empty"
                    error_code = 55
                    log_error()
                    continue          

                # NOA 직전 청구항 가져오기
                try:
                    final_claims = fetch_rejected_claims(noa_document_identifier, app_number, sorted_documents)
                except Exception as e:
                    print(f"❌ Failed to fetch final claims for application {app_number}: {e}")
                    error_message = f"Failed to fetch or parse final claims: {e}"
                    error_code = 56
                    log_error()
                    continue
                
                # spec text 파일명 변경 (application)
                formatted_record_number = f"{successful_record_count + 1:05d}"
                spec_text_path = os.path.join("./data/spec_app/text", f"spec_txt_r{formatted_record_number}_{app_number}.txt")
                with open(spec_text_path, "w") as f:
                    f.write(desc)

                # 인용된 특허들의 spec 텍스트는 ./data/spec_cited/text 경로에 spec_text_{cited_patent["referenceIdentifier"]}.txt 파일로 저장
                for cited_patent in patents_cited:
                    cited_spec_text_path = os.path.join("./data/spec_cited/text", f"spec_txt_{cited_patent['referenceIdentifier']}.txt")
                    with open(cited_spec_text_path, "w") as f:
                        f.write(cited_patent["spec"])
                
                # drw는 ./data/spec_application/image 경로에 spec_image_{app_number}.pdf 파일로 저장
                # 없으면 저장하지 않음
                if drw:
                    drw_path = os.path.join("./data/spec_app/image", f"spec_img_r{formatted_record_number}_{app_number}.pdf")
                    with open(drw_path, "wb") as f:
                        f.write(drw)
                
                # 인용된 특허들의 drawing은 ./data/spec_cited/image 경로에 spec_image_{cited_patent["referenceIdentifier"]}.pdf 파일로 저장
                for cited_patent in patents_cited:
                    cited_drw_path = os.path.join("./data/spec_cited/image", f"spec_img_{cited_patent['referenceIdentifier']}.pdf")
                    with open(cited_drw_path, "wb") as f:
                        f.write(cited_patent["drawing"])

                record = {
                    "id": successful_record_count + 1,
                    "abstract": abstract,
                    "initialClaims": initial_claims,
                    "finalClaims": final_claims,
                    "CTNFDocumentIdentifier": data["obsoleteDocumentIdentifier"],
                    "CTNFBodyText": data["CTNFBodyText"],
                    "NOABodyText": noa_body_text,
                    "applicationNumber": app_number,
                    "patentsCitedByExaminer": [
                        {"referenceIdentifier": cited_patent["referenceIdentifier"], "abstract": cited_patent["abstract"], "claims": cited_patent["claims"]} for cited_patent in patents_cited
                    ],
                    **metadata,
                }

                # 레코드 JSON 파일 저장
                successful_record_count += 1
                output_path = os.path.join(output_dir, f"rec_r{formatted_record_number}_{app_number}.json")
                with open(output_path, "w") as f:
                    json.dump(record, f, indent=4)
                print(f"✅ Record {formatted_record_number} saved to {output_path}.")
                
                final_data.append(record)
                print(f"Record {formatted_record_number} processed in {time.time() - start_time:.2f} seconds.")
                
                # 로그 기록
                log_error()

            start_Num += 100
            if start_Num >= 10000:
                print(f"Resetting start_Num from {start_Num} to 0")
                start_Num = 0
                # 새로운 error log 파일 생성
                error_log_path = f"./data/error_report/error_rec_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"
                # CSV 파일 헤더 생성
                with open(error_log_path, "w") as f:
                    f.write("pre_num,rec_num,app_num,error_code,error_message,timestamp\n")
                print(f"Created new error log file: {error_log_path}")
            print(f"Moving to next batch with start_Num = {start_Num}")
            time.sleep(5)  # API 요청 간 간격 두기
            
        except Exception as e:
            print(f"Error occurred in batch starting from {start_Num}: {e}")
            print("Retrying after 5 seconds...")
            time.sleep(5)
            continue
    
    return final_data

result = main(from_date, to_date)
print("All records have been processed and saved.")