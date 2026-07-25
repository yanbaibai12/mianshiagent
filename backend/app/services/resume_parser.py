class ResumeParser:
    @staticmethod
    def parse_pdf(file_path: str) -> str:
        import fitz  # PyMuPDF

        text = ""
        with fitz.open(file_path) as doc:
            for page in doc:
                text += page.get_text()
        return text.strip()

    @staticmethod
    def parse_docx(file_path: str) -> str:
        from docx import Document

        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs).strip()

    @staticmethod
    def parse(file_path: str) -> str:
        ext = file_path.lower().split(".")[-1]
        if ext == "pdf":
            return ResumeParser.parse_pdf(file_path)
        elif ext in ("docx", "doc"):
            return ResumeParser.parse_docx(file_path)
        else:
            raise ValueError(f"不支持的文件格式: {ext}")
