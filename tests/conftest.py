import pymupdf
import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.services.storage import LocalFileStorage


def _text_pdf(body: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), body, fontsize=11)
    return doc.tobytes()


def _image_only_pdf(caption: str = "SCANNED INVOICE - NO TEXT LAYER") -> bytes:
    """Render a page to a raster and wrap it in a fresh PDF -> no text layer."""
    src = pymupdf.open(stream=_text_pdf(caption), filetype="pdf")
    pix = src[0].get_pixmap(dpi=150)
    out = pymupdf.open()
    page = out.new_page(width=pix.width, height=pix.height)
    page.insert_image(page.rect, pixmap=pix)
    return out.tobytes()


@pytest.fixture
def text_invoice_pdf() -> bytes:
    return _text_pdf(
        "ACME LEGAL SERVICES - INVOICE\n"
        "Invoice Number: INV-2025-001\n"
        "Billed To: Compass Data and AI\n"
        "Consulting services rendered during June 2025\n"
        "Subtotal: 1000.00   Tax: 50.00   Total: 1050.00\n"
    )


@pytest.fixture
def image_only_pdf() -> bytes:
    return _image_only_pdf()


@pytest.fixture
def garbled_pdf() -> bytes:
    # Many characters, almost no letters: mimics a broken font/cmap encoding.
    return _text_pdf("&-'\"+=,&28>3136 %$#@ 4056078172 >>>\n" * 30)


@pytest.fixture
def encrypted_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "confidential invoice")
    return doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user"
    )


@pytest.fixture
def api_engine(tmp_path):
    """Point the process-wide engine at an isolated file database."""
    from sqlmodel import SQLModel, create_engine

    from app.core import database

    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}", connect_args={"check_same_thread": False}
    )
    database.set_engine(engine)
    SQLModel.metadata.create_all(engine)
    yield engine
    database.set_engine(None)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def storage(tmp_path):
    return LocalFileStorage(tmp_path)
