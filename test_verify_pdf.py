from collections import Counter
from app.services.document_loader import DocumentLoader

with open(r"C:\Users\Lenovo\mm\delta_run_knife_guide.pdf", "rb") as f:
    content = f.read()

chunks = DocumentLoader.load_and_split(content, "delta_run_knife_guide.pdf")
print("TOTAL_CHUNKS:", len(chunks))
print("TYPES:", dict(Counter(d.metadata.get("chunk_type") for d in chunks)))

for d in chunks:
    if d.metadata.get("chunk_type") == "table":
        print("===== TABLE SAMPLE =====")
        print(d.page_content[:400])
        break
for d in chunks:
    if d.metadata.get("chunk_type") == "image":
        print("===== IMAGE SAMPLE =====")
        print(d.page_content[:300])
        break