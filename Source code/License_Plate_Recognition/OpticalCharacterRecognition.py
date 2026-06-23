import easyocr

reader = easyocr.Reader(['en'], gpu=False)

def ocr_vietnamese_plate(plate_image):
    if plate_image is None: return ""
    try:
        results = reader.readtext(plate_image, detail=1)
        results.sort(key=lambda x: (x[0][0][1], x[0][0][0]))

        full_text = ""
        for (bbox, text, prob) in results:
            clean_text = "".join(e for e in text if e.isalnum())
            full_text += clean_text.upper()
        return full_text
    except Exception as e:
        return ""

def check_if_string_in_file(file_path, search_str):
    try:
        with open(file_path, 'r') as f:
            lines = [line.strip().upper() for line in f.readlines()]
            return search_str.upper() in lines
    except Exception:
        return False