"""Bounded CSV/XLSX ingestion for authenticated teacher uploads."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, BadZipFile
import pandas as pd


def read_score_upload(data: bytes, name: str) -> pd.DataFrame:
    if len(data) > 5 * 1024 * 1024:
        raise ValueError("Upload a file of at most 5 MB.")
    suffix = Path(name).suffix.lower()
    if suffix == ".csv":
        try:
            frame = pd.read_csv(BytesIO(data), encoding="utf-8-sig", nrows=1001)
        except (UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError):
            raise ValueError("Use a non-empty UTF-8 CSV file matching the template.") from None
    elif suffix == ".xlsx":
        try:
            with ZipFile(BytesIO(data)) as archive:
                infos = archive.infolist()
                if len(infos) > 1000 or sum(i.file_size for i in infos) > 30 * 1024 * 1024:
                    raise ValueError("This workbook is too large when decompressed. Export the needed rows to CSV.")
                if any(i.file_size > 1024 * 1024 and i.file_size / max(1, i.compress_size) > 200 for i in infos):
                    raise ValueError("This workbook has an unsafe compression ratio. Use CSV instead.")
            frame = pd.read_excel(BytesIO(data), nrows=1001, engine="openpyxl")
        except BadZipFile:
            raise ValueError("Use an unencrypted .xlsx workbook or UTF-8 CSV.") from None
    else:
        raise ValueError("Only .csv and .xlsx files are accepted.")
    if len(frame) > 1000 or len(frame.columns) > 7:
        raise ValueError("Use at most 1,000 rows and the 6 required columns plus optional exam_kind.")
    return frame
