import fitz
import base64
from io import BytesIO
from PIL import Image
from tqdm import tqdm
import os


def convert_pdf_to_base64_images(pdf_path):
    doc = fitz.open(pdf_path)
    base64_images = []

    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img = Image.open(BytesIO(pix.tobytes("png")))
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        base64_images.append(f"data:image/png;base64,{img_str}")
    
    return base64_images


def describe_pdf_as_images(pdf_path, llm, prompt):
    base64_images = convert_pdf_to_base64_images(pdf_path)

    messages = []
    print("📄 Preparing image-to-markdown prompts...")
    for b64 in tqdm(base64_images, desc="Encoding Pages"):
        messages.append([
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": b64}},
                    {"type": "text", "text": prompt}
                ]
            }
        ])

    print("🧠 Sending pages to LLM for description...")
    responses = list(tqdm(llm.batch(messages), desc="LLM Processing", total=len(messages)))

    return "".join([resp.content for resp in responses])