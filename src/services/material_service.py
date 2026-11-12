"""Carga y gestión de materiales académicos asociados a un curso."""

from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath
from typing import Callable, Optional
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError as DocxPackageNotFoundError
from lxml.etree import XMLSyntaxError
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from pptx import Presentation
from pptx.exc import PackageNotFoundError as PptxPackageNotFoundError
from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError

from src.domain.entities import CourseMaterial, CourseMaterialContent
from src.repositories.interfaces import UnitOfWork
from src.services.errors import CourseNotFoundError, SessionNotFoundError

UnitOfWorkFactory = Callable[[], UnitOfWork]

MAX_MATERIAL_FILE_BYTES = 10 * 1024 * 1024
MAX_MATERIAL_TEXT_CHARS = 500_000
MAX_OFFICE_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_OFFICE_ENTRIES = 1000
MAX_PDF_PAGES = 500

SUPPORTED_MATERIAL_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf": "application/pdf",
}
_OFFICE_PACKAGE_PARTS = {
    ".docx": "word/document.xml",
    ".pptx": "ppt/presentation.xml",
    ".xlsx": "xl/workbook.xml",
}


class MaterialFormatError(ValueError):
    """El documento no está soportado, es inválido o no se puede extraer."""


class CourseMaterialNotFoundError(LookupError):
    """El material solicitado no existe dentro del curso indicado."""


class CourseMaterialService:
    def __init__(self, uow_factory: UnitOfWorkFactory):
        self._uow_factory = uow_factory

    def list_for_course(self, course_id: int) -> list[CourseMaterial]:
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            return uow.course_materials.list_by_course(course_id)

    def upload(
        self,
        course_id: int,
        file_name: str,
        file_data: bytes,
        title: Optional[str] = None,
        topic: Optional[str] = None,
        class_session_id: Optional[int] = None,
    ) -> CourseMaterial:
        clean_file_name, content_type, extracted_text = self._prepare_file(file_name, file_data)
        clean_title = self._clean_label(title or PurePosixPath(clean_file_name).stem, "título")
        clean_topic = self._clean_optional_label(topic, "tema")
        with self._uow_factory() as uow:
            self._validate_course_and_session(uow, course_id, class_session_id)
            material = uow.course_materials.create(
                course_id=course_id,
                class_session_id=class_session_id,
                file_name=clean_file_name,
                title=clean_title,
                topic=clean_topic,
                content_type=content_type,
                size_bytes=len(file_data),
                file_data=file_data,
                extracted_text=extracted_text,
            )
            uow.commit()
            return material

    def get_content(self, course_id: int, material_id: int) -> CourseMaterialContent:
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            content = uow.course_materials.get_content(course_id, material_id)
        if content is None:
            raise CourseMaterialNotFoundError(
                f"El material {material_id} no existe en el curso {course_id}."
            )
        return content

    def replace_file(
        self, course_id: int, material_id: int, file_name: str, file_data: bytes
    ) -> CourseMaterial:
        clean_file_name, content_type, extracted_text = self._prepare_file(file_name, file_data)
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            material = uow.course_materials.replace_file(
                course_id=course_id,
                material_id=material_id,
                file_name=clean_file_name,
                content_type=content_type,
                size_bytes=len(file_data),
                file_data=file_data,
                extracted_text=extracted_text,
            )
            if material is None:
                raise CourseMaterialNotFoundError(
                    f"El material {material_id} no existe en el curso {course_id}."
                )
            uow.commit()
            return material

    def delete(self, course_id: int, material_id: int) -> None:
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            if not uow.course_materials.delete(course_id, material_id):
                raise CourseMaterialNotFoundError(
                    f"El material {material_id} no existe en el curso {course_id}."
                )
            uow.commit()

    @staticmethod
    def _require_course(uow: UnitOfWork, course_id: int) -> None:
        if uow.courses.get(course_id) is None:
            raise CourseNotFoundError(f"Curso {course_id} no encontrado.")

    @classmethod
    def _validate_course_and_session(
        cls, uow: UnitOfWork, course_id: int, class_session_id: Optional[int]
    ) -> None:
        cls._require_course(uow, course_id)
        if class_session_id is not None:
            session = uow.class_sessions.get(class_session_id)
            if session is None or session.course_id != course_id:
                raise SessionNotFoundError(
                    f"La sesión {class_session_id} no existe en el curso {course_id}."
                )

    @staticmethod
    def _clean_label(value: str, label: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise MaterialFormatError(f"El {label} no puede estar vacío.")
        if len(cleaned) > 255:
            raise MaterialFormatError(f"El {label} no puede superar los 255 caracteres.")
        return cleaned

    @classmethod
    def _clean_optional_label(cls, value: Optional[str], label: str) -> Optional[str]:
        if value is None or not value.strip():
            return None
        return cls._clean_label(value, label)

    @classmethod
    def _prepare_file(cls, file_name: str, file_data: bytes) -> tuple[str, str, str]:
        clean_name = PurePosixPath((file_name or "").replace("\\", "/")).name.strip()
        if not clean_name or len(clean_name) > 255:
            raise MaterialFormatError("El nombre del archivo no es válido.")
        extension = PurePosixPath(clean_name).suffix.lower()
        content_type = SUPPORTED_MATERIAL_TYPES.get(extension)
        if content_type is None:
            raise MaterialFormatError("Solo se admiten archivos .pptx, .docx, .xlsx o .pdf.")
        if not file_data:
            raise MaterialFormatError("El archivo está vacío.")
        if len(file_data) > MAX_MATERIAL_FILE_BYTES:
            raise MaterialFormatError("El archivo supera el límite de 10 MB.")

        if extension == ".pdf":
            extracted_text = cls._extract_pdf(file_data)
        else:
            extracted_text = cls._extract_office(extension, file_data)
        extracted_text = extracted_text.strip()
        if not extracted_text:
            raise MaterialFormatError(
                "No se encontró texto extraíble en el archivo; no se puede usar como fuente."
            )
        if len(extracted_text) > MAX_MATERIAL_TEXT_CHARS:
            raise MaterialFormatError(
                "El texto extraído supera el límite de 500 000 caracteres."
            )
        return clean_name, content_type, extracted_text

    @classmethod
    def _extract_pdf(cls, file_data: bytes) -> str:
        try:
            reader = PdfReader(BytesIO(file_data), strict=True)
            if reader.is_encrypted:
                raise MaterialFormatError("No se admiten documentos PDF protegidos con contraseña.")
            if len(reader.pages) > MAX_PDF_PAGES:
                raise MaterialFormatError("El PDF supera el máximo de 500 páginas.")
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except MaterialFormatError:
            raise
        except (PdfReadError, PdfStreamError, ValueError, OSError, EOFError) as exc:
            raise MaterialFormatError("El archivo PDF está dañado o no se puede leer.") from exc

    @classmethod
    def _extract_office(cls, extension: str, file_data: bytes) -> str:
        try:
            with ZipFile(BytesIO(file_data)) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_OFFICE_ENTRIES:
                    raise MaterialFormatError("El documento contiene demasiados componentes.")
                if sum(entry.file_size for entry in entries) > MAX_OFFICE_UNCOMPRESSED_BYTES:
                    raise MaterialFormatError(
                        "El contenido descomprimido del documento supera el límite permitido."
                    )
                if _OFFICE_PACKAGE_PARTS[extension] not in archive.namelist():
                    raise MaterialFormatError(
                        f"El archivo no contiene una estructura válida de {extension}."
                    )

            if extension == ".docx":
                document = Document(BytesIO(file_data))
                paragraphs = [paragraph.text for paragraph in document.paragraphs]
                paragraphs.extend(
                    cell.text
                    for table in document.tables
                    for row in table.rows
                    for cell in row.cells
                )
                return "\n".join(paragraphs)
            if extension == ".pptx":
                presentation = Presentation(BytesIO(file_data))
                text = []
                for slide_number, slide in enumerate(presentation.slides, start=1):
                    slide_text = []
                    for shape in slide.shapes:
                        if shape.has_text_frame:
                            slide_text.extend(
                                paragraph.text for paragraph in shape.text_frame.paragraphs
                                if paragraph.text.strip()
                            )
                        if shape.has_table:
                            slide_text.extend(
                                cell.text
                                for row in shape.table.rows
                                for cell in row.cells
                                if cell.text.strip()
                            )
                    if slide_text:
                        text.append(f"Diapositiva {slide_number}")
                        text.extend(slide_text)
                return "\n".join(text)

            workbook = load_workbook(BytesIO(file_data), read_only=True, data_only=True)
            text = []
            try:
                for worksheet in workbook.worksheets:
                    sheet_text = []
                    for row in worksheet.iter_rows(values_only=True):
                        values = [
                            str(value)
                            for value in row
                            if value is not None and str(value).strip()
                        ]
                        if values:
                            sheet_text.append(" | ".join(values))
                    if sheet_text:
                        text.append(worksheet.title)
                        text.extend(sheet_text)
            finally:
                workbook.close()
            return "\n".join(text)
        except MaterialFormatError:
            raise
        except (
            BadZipFile,
            DocxPackageNotFoundError,
            InvalidFileException,
            KeyError,
            PptxPackageNotFoundError,
            RuntimeError,
            ValueError,
            OSError,
            EOFError,
            XMLSyntaxError,
        ) as exc:
            raise MaterialFormatError(
                "El documento está dañado o no coincide con su extensión."
            ) from exc
