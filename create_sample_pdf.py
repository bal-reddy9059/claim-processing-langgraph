import fitz
from pathlib import Path

path = Path('final_image_protected.pdf')
doc = fitz.open()
page = doc.new_page()
page.insert_text((72, 72), 'Sample Claim PDF\nfinal_image_protected.pdf\nThis is a placeholder sample PDF for testing.', fontsize=14)
doc.save(path)
print('created', path.exists(), path)
