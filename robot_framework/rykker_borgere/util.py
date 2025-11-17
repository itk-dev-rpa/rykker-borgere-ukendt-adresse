"""Utility functions for the Rykker Borgere project."""
from pathlib import Path
from datetime import datetime
import subprocess

from docxtpl import DocxTemplate

from itk_dev_shared_components.kmd_nova.nova_objects import JournalNote
from robot_framework import config


def fill_template(template_path: str, output_path: str, name: str, date: datetime, case_number: str) -> Path:
    """Fill a template with the given context."""
    context = {
        "Fornavn": name,
        "dato": date.strftime(format="%d/%m/%Y"),
        "Sagsnummer": case_number
    }
    doc = DocxTemplate(template_path)
    doc.render(context)
    doc.save(filename=output_path)
    return Path(output_path)

def convert_docx_to_pdf(path_to_docx: Path, tmpdir: str):
    """Convert a docx file to a PDF file."""
    subprocess.run(args=[config.PATH_TO_LIBREOFFICE, "--headless", "--convert-to", "pdf", "--outdir", tmpdir, str(path_to_docx)], check=True)
    return Path(tmpdir) / f"{path_to_docx.stem}.pdf"

def get_step(notes: list[JournalNote]) -> tuple[int, JournalNote]:
    """Get the next step number for a case."""
    highest_step = 0
    new_step = 0
    newest_note = None
    for note in notes:
        note_title = note.title
        if note_title.startswith(config.NOTE_PREFIX):
            highest_step = max(highest_step, int(note_title.split(config.NOTE_PREFIX)[1].strip()))
            new_step = highest_step + 1
            newest_note = note
    return new_step, newest_note
