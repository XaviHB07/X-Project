import io

import pytest
from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from src.repositories.in_memory.repository_impl import InMemoryDatabase
from src.repositories.in_memory.unit_of_work import InMemoryUnitOfWork
from src.services.errors import SessionNotFoundError
from src.services.material_service import CourseMaterialService, MaterialFormatError


def make_docx(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_pptx(text: str) -> bytes:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    shape = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
    shape.text_frame.text = text
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def make_xlsx(text: str) -> bytes:
    workbook = Workbook()
    workbook.active.append([text])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def make_pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=100)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
    })
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 10 50 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def material_context():
    database = InMemoryDatabase()
    uow_factory = lambda: InMemoryUnitOfWork(database)
    with uow_factory() as uow:
        course = uow.courses.create("Materiales")
        other_course = uow.courses.create("Otro curso")
        other_session = uow.class_sessions.create(other_course.id)
        uow.commit()
    return course.id, other_course.id, other_session.id, CourseMaterialService(uow_factory)


@pytest.mark.parametrize(
    ("file_name", "file_data", "expected_text"),
    [
        ("tema.docx", make_docx("Texto del documento"), "Texto del documento"),
        ("tema.pptx", make_pptx("Texto de la diapositiva"), "Texto de la diapositiva"),
        ("tema.xlsx", make_xlsx("Texto de la hoja"), "Texto de la hoja"),
        ("tema.pdf", make_pdf("Texto del PDF"), "Texto del PDF"),
    ],
)
def test_upload_extracts_and_persists_supported_document_text(
    material_context, file_name, file_data, expected_text
):
    course_id, _, _, service = material_context

    material = service.upload(
        course_id,
        file_name,
        file_data,
        title="Unidad",
        topic="Tema de prueba",
    )

    assert material.title == "Unidad"
    assert material.topic == "Tema de prueba"
    assert material.file_name == file_name
    content = service.get_content(course_id, material.id)
    assert content.file_data == file_data
    assert expected_text in content.extracted_text
    assert [item.id for item in service.list_for_course(course_id)] == [material.id]


def test_replace_updates_original_and_extracted_text(material_context):
    course_id, _, _, service = material_context
    original = service.upload(course_id, "original.docx", make_docx("Texto inicial"))

    updated = service.replace_file(
        course_id, original.id, "reemplazo.docx", make_docx("Texto actualizado")
    )

    assert updated.id == original.id
    assert updated.title == original.title
    assert updated.file_name == "reemplazo.docx"
    content = service.get_content(course_id, original.id)
    assert content.file_data == make_docx("Texto actualizado")
    assert "Texto actualizado" in content.extracted_text
    assert "Texto inicial" not in content.extracted_text


def test_rejects_unsupported_and_invalid_files(material_context):
    course_id, _, _, service = material_context

    with pytest.raises(MaterialFormatError, match="Solo se admiten"):
        service.upload(course_id, "tema.doc", b"no soportado")
    with pytest.raises(MaterialFormatError, match="dañado"):
        service.upload(course_id, "tema.docx", b"no es un documento Office")


def test_does_not_associate_material_with_a_session_from_another_course(material_context):
    course_id, _, other_session_id, service = material_context

    with pytest.raises(SessionNotFoundError):
        service.upload(
            course_id,
            "tema.docx",
            make_docx("Texto"),
            class_session_id=other_session_id,
        )
