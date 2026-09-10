import os
import re
import pytesseract
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
from PIL import Image, ImageEnhance

# Configure Tesseract path for Windows
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Reference ranges 
REFERENCE_RANGES = {
    "haemoglobin": {"min": 12.0, "max": 17.5, "unit": "g/dL"},
    "hemoglobin": {"min": 12.0, "max": 17.5, "unit": "g/dL"},
    "rbc count": {"min": 4.0, "max": 6.0, "unit": "million/uL"},
    "pcv": {"min": 35.0, "max": 45.0, "unit": "%"},
    "mcv": {"min": 80.0, "max": 100.0, "unit": "fL"},
    "mch": {"min": 27.0, "max": 33.0, "unit": "pg"},
    "mchc": {"min": 32.0, "max": 36.0, "unit": "g/dL"},
    "rdw": {"min": 9.0, "max": 17.0, "unit": "%"},
    "total wbc count": {"min": 4000, "max": 11000, "unit": "cells/cu.mm"},
    "neutrophils": {"min": 40.0, "max": 75.0, "unit": "%"},
    "lymphocytes": {"min": 20.0, "max": 45.0, "unit": "%"},
    "eosinophils": {"min": 0.0, "max": 6.0, "unit": "%"},
    "monocytes": {"min": 0.0, "max": 10.0, "unit": "%"},
    "basophils": {"min": 0.0, "max": 1.0, "unit": "%"},
    "platelet count": {"min": 150000, "max": 450000, "unit": "cells/cu.mm"},
    "serum creatinine": {"min": 0.6, "max": 1.2, "unit": "mg/dL"},
    "creatinine": {"min": 0.6, "max": 1.2, "unit": "mg/dL"},
    "blood urea nitrogen": {"min": 7.0, "max": 20.0, "unit": "mg/dL"},
    "bun": {"min": 7.0, "max": 20.0, "unit": "mg/dL"},
    "serum urea": {"min": 15.0, "max": 45.0, "unit": "mg/dL"},
    "urea": {"min": 15.0, "max": 45.0, "unit": "mg/dL"},
    "uric acid": {"min": 3.5, "max": 7.2, "unit": "mg/dL"},
    "serum uric acid": {"min": 3.5, "max": 7.2, "unit": "mg/dL"},
    "sodium": {"min": 135.0, "max": 145.0, "unit": "mmol/L"},
    "potassium": {"min": 3.5, "max": 5.0, "unit": "mmol/L"},
    "chloride": {"min": 96.0, "max": 106.0, "unit": "mmol/L"},
    "serum calcium": {"min": 8.5, "max": 10.2, "unit": "mg/dL"}
}

def extract_text(file_path):
    """Extracts text from an Image file with OCR enhancement."""
    text = ""
    try:
        image = Image.open(file_path)
        image = image.convert('L')
        width, height = image.size
        image = image.resize((width * 2, height * 2), Image.Resampling.LANCZOS)
        
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.0)
        
        config = r'--oem 3 --psm 6'
        text = pytesseract.image_to_string(image, config=config)
        
        if not text.strip():
            text = pytesseract.image_to_string(image)
    except Exception as e:
        print(f"Error reading file: {e}")
        
    return text.lower()

def analyze_report(text):
    """Parses text and compares found values to reference ranges."""
    results = []
    found_keys = set()
    
    for param, ranges in REFERENCE_RANGES.items():
        if param in found_keys:
            continue
            
        pattern = re.compile(rf"\b{param}\b[^\d\n]*([\d\.]+)")
        match = pattern.search(text)
        
        if match:
            try:
                val_str = match.group(1)
                if val_str == ".": 
                    continue
                    
                value = float(val_str)
                status = "NORMAL"
                
                if value < ranges['min']:
                    status = "LOW"
                elif value > ranges['max']:
                    status = "HIGH"
                
                results.append({
                    "parameter": param.title(),
                    "value": value,
                    "status": status,
                    "min": ranges['min'],
                    "max": ranges['max'],
                    "unit": ranges['unit']
                })
                found_keys.add(param)
            except ValueError:
                continue
                
    return results

def extract_blood_data(file_path):
    """Bridge function to run analysis on uploaded image and return Django response dict."""
    if not os.path.exists(file_path):
        return {"diagnosis": "Error", "details": "Uploaded file not found."}

    text = extract_text(file_path)
    
    if not text.strip():
        return {"diagnosis": "OCR Failed", "details": "Could not extract text from document."}

    analysis = analyze_report(text)
    
    if not analysis:
        return {"diagnosis": "No Parameters Found", "details": "Could not match any standard lab parameters."}

    highs = [r for r in analysis if r['status'] == 'HIGH']
    lows = [r for r in analysis if r['status'] == 'LOW']
    normals = [r for r in analysis if r['status'] == 'NORMAL']
    
    report_lines = []
    report_lines.append(" BLOOD REPORT ANALYSIS REPORT")
    report_lines.append("--------------------------------------------------")

    if highs:
        report_lines.append("\n HIGH VALUES:")
        for r in highs:
            report_lines.append(f"  - {r['parameter']}: {r['value']} {r['unit']} (Normal: {r['min']} - {r['max']})")

    if lows:
        report_lines.append("\n LOW VALUES:")
        for r in lows:
            report_lines.append(f"  - {r['parameter']}: {r['value']} {r['unit']} (Normal: {r['min']} - {r['max']})")

    if normals:
        report_lines.append("\n NORMAL VALUES:")
        for r in normals:
            report_lines.append(f"  - {r['parameter']}: {r['value']} {r['unit']}")

    report_lines.append("\n--------------------------------------------------")

    overall_status = []
    if highs:
        overall_status.append(f"{len(highs)} High Parameter(s)")
    if lows:
        overall_status.append(f"{len(lows)} Low Parameter(s)")
    if not highs and not lows:
        overall_status.append("All Measured Parameters Normal")

    return {
        "diagnosis": f"Analysis Complete: {', '.join(overall_status)}",
        "details": "\n".join(report_lines)
    }