import json
import os
from docx import Document

def main():
    # 현재 디렉토리와 상위 디렉토리 경로 설정
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    
    # 입력과 출력 폴더 경로 설정
    input_folder = os.path.join(parent_dir, "data", "record")
    output_folder = os.path.join(parent_dir, "data", "rawCTNF")
    
    # 출력 폴더가 없으면 생성
    os.makedirs(output_folder, exist_ok=True)
    
    # record 폴더의 모든 JSON 파일 처리
    for file_name in os.listdir(input_folder):
        if file_name.endswith(".json"):
            file_path = os.path.join(input_folder, file_name)
            
            # JSON 파일 읽기
            with open(file_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            
            # CTNFBodyText 추출
            ctnf_body_text = data.get("CTNFBodyText", "").strip()
            application_number = data.get("applicationNumber", "").strip()
            
            # 출력 파일 이름 생성 (record_0_15154727.json -> rawCTNF_0_15154727.docx)
            file_index = file_name.split('_')[1].split('.')[0]  # 0
            output_file_name = f"rawCTNF_{file_index}_{application_number}.docx"
            output_path = os.path.join(output_folder, output_file_name)
            
            # docx 파일 생성
            doc = Document()
            doc.add_paragraph(ctnf_body_text)
            
            # docx 파일로 저장
            doc.save(output_path)
            
            print(f"Exported {output_file_name}")

if __name__ == "__main__":
    main()
