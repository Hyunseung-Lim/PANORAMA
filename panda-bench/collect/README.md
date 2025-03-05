# PANOMA Dataset Generation Process

This document describes how the PANOMA dataset was generated for the benchmark project. The PANOMA dataset consists of patent applications and their corresponding office actions from the USPTO (United States Patent and Trademark Office), focusing on applications that received a CTNF (Non-Final Rejection) and eventually a NOA (Notice of Allowance).

## Dataset Overview

The PANOMA dataset was created by collecting patent application data through USPTO's public APIs. The data was processed and structured to support the evaluation of patent examination processes, particularly how applications evolve from initial rejection to eventual allowance.

## Data Collection Process

The data collection process followed these steps:

1. **Fetch CTNF Documents**: Retrieved Non-Final Rejection documents within a specified date range using the USPTO OA Text Retrieval API.

2. **Filter Valid Applications**: Several filters were applied to ensure data quality:
   - Only first CTNF documents for each application were included
   - Applications that received a Final Rejection (CTFR) were excluded
   - Only applications that eventually received a Notice of Allowance (NOA) were included
   - Applications where abstract or specification was modified between CTNF and NOA were excluded

3. **Extract Application Data**: For each valid application, the system collected:
   - Application metadata
   - Abstract
   - Initial claims (at the time of CTNF)
   - Final claims (at the time of NOA)
   - Specification text
   - Drawings (if available)

4. **Extract Citation Data**: Patents cited by the examiner in the CTNF document were extracted, including:
   - Reference identifier
   - Abstract
   - Claims
   - Specification text
   - Drawings

5. **Create Structured Records**: All collected data was organized into JSON records and saved with associated text and image files.

## Dataset Structure

The generated PANOMA dataset consists of:

- **JSON Records**: Stored in `./data/record/` with filename format `rec_rXXXXX_APPNUMBER.json`
- **Application Specifications**: Text stored in `./data/spec_app/text/`
- **Application Drawings**: PDF files stored in `./data/spec_app/image/`
- **Cited Patent Specifications**: Text stored in `./data/spec_cited/text/`
- **Cited Patent Drawings**: PDF files stored in `./data/spec_cited/image/`
- **Error Logs**: CSV files stored in `./data/error_report/`

Each JSON record contains:
- Application ID and metadata
- Abstract
- Initial and final claims
- CTNF and NOA document text
- Patents cited by the examiner

## CTNF Parsing Process

The CTNF documents were parsed using GPT-4o through the `CTNFparser.py` script. This script extracts structured information from the raw CTNF text using a detailed prompt (`parsing_prompt.txt`) that guides the model to:

1. **Identify Claim Information**:
   - Extract claim numbers and their parent-child relationships
   - Determine which claims are rejected vs. allowed
   - Handle claim ranges and cancelled claims appropriately

2. **Extract Rejection Details**:
   - Identify the section codes (e.g., 102, 103) under which claims are rejected
   - Extract cited patents with standardized formatting
   - Capture detailed technical reasoning for each rejection

3. **Structure the Output**:
   - Generate a structured JSON with claims array containing:
     - Claim number and parent claim reference
     - Rejection status
     - Detailed reasons with section codes, cited patents, and explanations

The parsed CTNF data is stored in `./data/parsed_CTNF/` with filename format `pC_rXXXXX_APPNUMBER.json`.

## Data Validation Process

The dataset underwent a two-stage validation process using the `validation.py` script:

1. **Basic Validation**: Performed structural and consistency checks:
   - Compared claim counts between CTNF documents and record data
   - Verified cited patents match between CTNF and record data
   - Filtered out cancelled claims
   - Validated JSON structure and content

2. **GPT Validation**: Used GPT-4o to perform deeper semantic validation:
   - Verified section codes (102/103) match between parsed CTNF data and original text
   - Confirmed cited patents were correctly extracted and matched
   - Validated claim-by-claim rejection reasons

The validation process generated detailed error logs and a validation results file that tracked which records passed each validation stage.

## Benchmark Dataset Creation

For the benchmark project, a refined dataset was created from the raw PANOMA data using the `convert2bench.py` script. This script:
1. Filtered records to include only those with 102/103 rejections
2. Combined each record (`rec_rXXXXX_APPNUMBER.json`) with its corresponding parsed CTNF data (`pC_rXXXXX_APPNUMBER.json`)
3. Created a standardized benchmark format for evaluation
4. Logged any errors encountered during the conversion process

## Dataset Generation Tools

The following scripts were used in the dataset generation process:

1. `main.py`: The primary script for collecting and processing the raw patent data
2. `CTNFparser.py`: Script for parsing CTNF documents using GPT-4o
3. `validation.py`: Script for validating the collected and parsed data
4. `convert2bench.py`: Script for converting raw data to benchmark format

## Error Handling

During the dataset generation process, various error types were logged with specific error codes:
- 10: Non-first CTNF document
- 20: Application received a Final Rejection
- 30-32: NOA document issues
- 40: Abstract or specification modified between CTNF and NOA
- 50-56: Issues with fetching application documents
- 60-61: Issues with cited patents
- 70: Duplicate application
- 100-170: Validation errors (claim count mismatches, citation mismatches, etc.)
