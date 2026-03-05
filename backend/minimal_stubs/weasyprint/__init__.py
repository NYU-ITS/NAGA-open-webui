# Stub for local dev: weasyprint requires libgobject (GTK/Linux), unavailable on macOS.
# PDF export will silently return empty bytes when this stub is active.

class HTML:
    def __init__(self, *args, **kwargs):
        pass

    def write_pdf(self, *args, **kwargs):
        return b''
