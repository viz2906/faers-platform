"""
Parse FDA FAERS ASCII files into cleaned DataFrames

FAERS ASCII files are pipe-delimited ($) text files with latin-1 encoding.
This module handles all the quirks: mixed case headers, bad lines, 
inconsistent date formats, etc.
"""

import glob
import os
import re

import pandas as pd
from loguru import logger

# FAERS File Definitions
DELIMITER = "$"
ENCODING = "latin-1"      # CRITICAL: FAERS is NOT UTF-8

# Table file name patterns (FDA uses inconsistent naming across years)
TABLE_PATTERNS = {
    "DEMO": ["DEMO*.txt", "demo*.txt"],
    "DRUG": ["DRUG*.txt", "drug*.txt"],
    "REAC": ["REAC*.txt", "reac*.txt"],
    "OUTC": ["OUTC*.txt", "outc*.txt"],
    "RPSR": ["RPSR*.txt", "rpsr*.txt"],
    "THER": ["THER*.txt", "ther*.txt"],
    "INDI": ["INDI*.txt", "indi*.txt"],
}

# Explicit dtype definitions to prevent pandas guessing wrong types
TABLE_DTYPES = {
    "DEMO": {
        "report_id": str,
        "caseid": str,
        "caseversion": "Int64",      # nullable int
        "i_f_code": str,
        "event_dt": str,
        "mfr_dt": str,
        "init_fda_dt": str,
        "fda_dt": str,
        "rept_cod": str,
        "auth_num": str,
        "mfr_num": str,
        "mfr_sndr": str,
        "lit_ref": str,
        "age": "Float64",
        "age_cod": str,
        "age_grp": str,
        "sex": str,
        "e_sub": str,
        "wt": "Float64",
        "wt_cod": str,
        "rept_dt": str,
        "to_mfr": str,
        "occp_cod": str,
        "reporter_country": str,
        "occr_country": str,
    },
    "DRUG": {
        "report_id": str,
        "caseid": str,
        "drug_seq": "Int64",
        "role_cod": str,
        "drugname": str,
        "prod_ai": str,
        "val_vbm": str,
        "route": str,
        "dose_vbm": str,
        "cum_dose_chr": str,
        "cum_dose_unit": str,
        "dechal": str,
        "rechal": str,
        "lot_num": str,
        "exp_dt": str,
        "nda_num": str,
        "dose_amt": "Float64",
        "dose_unit": str,
        "dose_form": str,
        "dose_freq": str,
    },
    "REAC": {
        "report_id": str,
        "caseid": str,
        "pt": str,
        "drug_rec_act": str,
    },
    "OUTC": {
        "report_id": str,
        "caseid": str,
        "outc_cod": str,
    },
    "RPSR": {
        "report_id": str,
        "caseid": str,
        "rpsr_cod": str,
    },
    "THER": {
        "report_id": str,
        "caseid": str,
        "drug_seq": "Int64",
        "start_dt": str,
        "end_dt": str,
        "dur": "Float64",
        "dur_cod": str,
    },
    "INDI": {
        "report_id": str,
        "caseid": str,
        "drug_seq": "Int64",
        "indi_pt": str,
    },
}

# Core Parser
def find_table_file(ascii_dir: str, table_name: str) -> str | None:
    """Find the file for a given table in the ASCII directory."""
    for pattern in TABLE_PATTERNS[table_name]:
        matches = glob.glob(os.path.join(ascii_dir, pattern))
        if matches:
            return matches[0]
    logger.warning(f"Could not find file for table {table_name} in {ascii_dir}")
    return None

def load_raw_table(filepath: str, table_name: str) -> pd.DataFrame:
    """Load a single FAERS ASCII table file into a raw DataFrame."""
    logger.info(f"Loading {table_name} from {filepath}")
    
    dtypes = TABLE_DTYPES.get(table_name, {})
    
    try:
        df = pd.read_csv(
            filepath,
            sep=DELIMITER,
            dtype=dtypes,
            encoding=ENCODING,
            on_bad_lines="skip",       # Skip malformed rows (common in FAERS)
            engine="python",           # More flexible than C engine for bad data
        )
    except Exception as e:
        logger.warning(f"Standard parse failed for {table_name}: {e}. Trying fallback...")
        # Fallback: read with no dtypes, fix later
        df = pd.read_csv(
            filepath,
            sep=DELIMITER,
            encoding=ENCODING,
            on_bad_lines="skip",
            engine="python",
            dtype=str,                 # Everything as string, fix types after
        )
    
    # Normalize column names: lowercase, strip whitespace
    df.columns = df.columns.str.lower().str.strip()
    
    # Rename primaryid to report_id for cross-source compatibility
    if "primaryid" in df.columns:
        df = df.rename(columns={"primaryid": "report_id"})
    
    logger.info(f"  Loaded {len(df):,} rows, {len(df.columns)} columns: {list(df.columns)}")
    return df

# Date Parsing
FAERS_DATE_FORMATS = [
    "%Y%m%d",    # 20240315 — most common
    "%Y%m",      # 202403 — month-level precision
    "%Y",        # 2024 — year-level precision
    "%m/%d/%Y",  # 03/15/2024 — some older records
    "%d/%m/%Y",  # 15/03/2024 — rare but exists
]

INVALID_DATES = {"", "0", "00000000", "00000", "0000", "99999999"}

def parse_faers_date(date_str) -> pd.Timestamp | None:
    """Parse FAERS date strings which come in many inconsistent formats."""
    if pd.isna(date_str):
        return None
    
    s = str(date_str).strip()
    if s in INVALID_DATES:
        return None
    
    # Remove non-numeric characters (some entries have slashes, dashes)
    s_clean = re.sub(r"[^0-9]", "", s)
    
    for fmt in FAERS_DATE_FORMATS:
        try:
            # Try numeric formats with cleaned string
            if fmt in ("%Y%m%d", "%Y%m", "%Y"):
                n_chars = len(fmt.replace("%", "").replace("Y", "YYYY").replace("m", "mm").replace("d", "dd"))
                parsed_str = s_clean
            else:
                parsed_str = s
            return pd.to_datetime(parsed_str, format=fmt)
        except (ValueError, TypeError):
            continue
    
    return None

# Age Normalization
AGE_TO_YEARS = {
    "YR":  1.0,
    "DEC": 10.0,
    "MON": 1.0 / 12.0,
    "WK":  1.0 / 52.18,
    "DY":  1.0 / 365.25,
    "HR":  1.0 / 8766.0,
}

def normalize_age_to_years(age: float, age_cod: str) -> float | None:
    """Convert age from any FAERS unit to decimal years."""
    if pd.isna(age) or age <= 0:
        return None
    
    unit = str(age_cod).strip().upper() if not pd.isna(age_cod) else "YR"
    factor = AGE_TO_YEARS.get(unit, 1.0)
    result = age * factor
    
    # Sanity check: cap at 150 years
    if result > 150:
        return None
    return round(result, 2)

# Weight Normalization
WEIGHT_TO_KG = {
    "KG":  1.0,
    "LBS": 0.453592,
    "GMS": 0.001,
}

def normalize_weight_to_kg(wt: float, wt_cod: str) -> float | None:
    """Convert weight to kilograms."""
    if pd.isna(wt) or wt <= 0:
        return None
    unit = str(wt_cod).strip().upper() if not pd.isna(wt_cod) else "KG"
    factor = WEIGHT_TO_KG.get(unit, 1.0)
    result = wt * factor
    if result > 700 or result < 0.1:  # Sanity: 0.1kg to 700kg
        return None
    return round(result, 2)

# Table-Specific Cleaning
def clean_demo(df: pd.DataFrame, quarter: str) -> pd.DataFrame:
    """Clean and enrich the DEMO (demographics) table."""
    logger.info(f"Cleaning DEMO table ({len(df):,} rows)")
    
    # Parse dates
    df["event_dt_parsed"] = df["event_dt"].apply(parse_faers_date)
    df["fda_dt_parsed"] = df["fda_dt"].apply(parse_faers_date)
    df["rept_dt_parsed"] = df.get("rept_dt", pd.Series(dtype=str)).apply(parse_faers_date)
    
    # Normalize age
    df["age_years"] = df.apply(
        lambda r: normalize_age_to_years(r.get("age"), r.get("age_cod")),
        axis=1,
    )
    
    # Normalize weight
    df["weight_kg"] = df.apply(
        lambda r: normalize_weight_to_kg(r.get("wt"), r.get("wt_cod")),
        axis=1,
    )
    
    # Standardize sex
    SEX_MAP = {
        "M": "Male", "m": "Male",
        "F": "Female", "f": "Female",
        "UNK": "Unknown", "NS": "Unknown",
    }
    df["sex_clean"] = df["sex"].map(SEX_MAP).fillna("Unknown")
    
    # Age groups
    def age_group(age):
        if pd.isna(age): return "Unknown"
        if age < 2: return "Neonate/Infant (<2y)"
        if age < 12: return "Child (2-11y)"
        if age < 18: return "Adolescent (12-17y)"
        if age < 45: return "Young Adult (18-44y)"
        if age < 65: return "Middle-Aged (45-64y)"
        return "Elderly (65+y)"
    
    df["age_group"] = df["age_years"].apply(age_group)
    
    # Quarter tag
    df["quarter"] = quarter
    
    # Ensure report_id is numeric
    df["report_id"] = pd.to_numeric(df["report_id"], errors="coerce")
    df["caseid"] = pd.to_numeric(df["caseid"], errors="coerce")
    
    # Drop rows with missing primary key
    before = len(df)
    df = df.dropna(subset=["report_id"])
    if before > len(df):
        logger.warning(f"  Dropped {before - len(df)} rows with null report_id")
    
    return df

def clean_drug(df: pd.DataFrame, quarter: str) -> pd.DataFrame:
    """Clean and enrich the DRUG table."""
    logger.info(f"Cleaning DRUG table ({len(df):,} rows)")
    
    # Normalize drug names to uppercase
    df["drugname_clean"] = (
        df["drugname"]
        .fillna("")
        .str.upper()
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )
    
    # Normalize active ingredient
    df["prod_ai_clean"] = (
        df["prod_ai"]
        .fillna("")
        .str.upper()
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )
    
    # Role code labels
    ROLE_MAP = {
        "PS": "Primary Suspect",
        "SS": "Secondary Suspect",
        "C":  "Concomitant",
        "I":  "Interacting",
    }
    df["drug_role"] = df["role_cod"].map(ROLE_MAP).fillna("Unknown")
    
    # Normalize route of administration
    df["route_clean"] = df["route"].fillna("Unknown").str.upper().str.strip()
    
    # Quarter
    df["quarter"] = quarter
    
    # Ensure PKs are numeric
    df["report_id"] = pd.to_numeric(df["report_id"], errors="coerce")
    df["caseid"] = pd.to_numeric(df["caseid"], errors="coerce")
    df["drug_seq"] = pd.to_numeric(df.get("drug_seq"), errors="coerce")
    
    df = df.dropna(subset=["report_id"])
    return df

def clean_reac(df: pd.DataFrame, quarter: str) -> pd.DataFrame:
    """Clean the REAC (reactions) table."""
    logger.info(f"Cleaning REAC table ({len(df):,} rows)")
    
    # Normalize MedDRA preferred terms
    df["pt_clean"] = (
        df["pt"]
        .fillna("")
        .str.strip()
        .str.title()   # Capitalize each word (MedDRA standard)
    )
    
    df["quarter"] = quarter
    df["report_id"] = pd.to_numeric(df["report_id"], errors="coerce")
    df = df.dropna(subset=["report_id", "pt"])
    
    logger.info(f"  {df['pt_clean'].nunique():,} unique MedDRA reaction terms")
    return df

def clean_outc(df: pd.DataFrame, quarter: str) -> pd.DataFrame:
    """Clean the OUTC (outcomes) table."""
    OUTC_LABELS = {
        "DE": "Death",
        "LT": "Life-Threatening",
        "HO": "Hospitalization",
        "DS": "Disability",
        "CA": "Congenital Anomaly",
        "RI": "Required Intervention",
        "OT": "Other Serious",
    }
    df["outcome_label"] = df["outc_cod"].map(OUTC_LABELS).fillna("Unknown")
    df["quarter"] = quarter
    df["report_id"] = pd.to_numeric(df["report_id"], errors="coerce")
    df = df.dropna(subset=["report_id", "outc_cod"])
    return df

def clean_ther(df: pd.DataFrame, quarter: str) -> pd.DataFrame:
    """Clean the THER (therapy dates) table."""
    df["start_dt_parsed"] = df["start_dt"].apply(parse_faers_date)
    df["end_dt_parsed"] = df["end_dt"].apply(parse_faers_date)
    
    # Normalize duration to days
    DUR_TO_DAYS = {"YR": 365.25, "MON": 30.44, "WK": 7, "DY": 1, "HR": 1/24}
    df["dur_days"] = df.apply(
        lambda r: (r.get("dur", None) or None) and
                  (r["dur"] * DUR_TO_DAYS.get(str(r.get("dur_cod", "DY")).strip().upper(), 1))
        if not pd.isna(r.get("dur")) else None,
        axis=1
    )
    
    df["quarter"] = quarter
    df["report_id"] = pd.to_numeric(df["report_id"], errors="coerce")
    df = df.dropna(subset=["report_id"])
    return df

def clean_indi(df: pd.DataFrame, quarter: str) -> pd.DataFrame:
    """Clean the INDI (indications) table."""
    df["indi_pt_clean"] = (
        df["indi_pt"]
        .fillna("")
        .str.strip()
        .str.title()
    )
    df["quarter"] = quarter
    df["report_id"] = pd.to_numeric(df["report_id"], errors="coerce")
    df = df.dropna(subset=["report_id"])
    return df

# Deduplication (Critical!)
def deduplicate_demo(demo_df: pd.DataFrame) -> pd.DataFrame:
    """
    FAERS has multiple versions of the same case (follow-up reports).
    Keep only the LATEST version (max caseversion) per caseid.
    This is the FDA-recommended approach.
    """
    logger.info(f"Deduplicating DEMO: {len(demo_df):,} rows → keeping latest caseversion per caseid")
    
    # Find the latest version per case
    demo_df["caseversion"] = pd.to_numeric(demo_df["caseversion"], errors="coerce").fillna(0)
    latest = (
        demo_df.groupby("caseid")["caseversion"]
        .max()
        .reset_index()
        .rename(columns={"caseversion": "max_version"})
    )
    
    deduped = demo_df.merge(
        latest,
        on="caseid",
        how="inner"
    )
    deduped = deduped[deduped["caseversion"] == deduped["max_version"]].drop(columns=["max_version"])
    
    # If still duplicates (same caseid + caseversion), keep first
    deduped = deduped.drop_duplicates(subset=["report_id"])
    
    logger.info(f"  After dedup: {len(deduped):,} unique cases ({len(demo_df) - len(deduped):,} duplicates removed)")
    return deduped

# Main Entry Point
def parse_quarter(ascii_dir: str, quarter: str, status_callback=None) -> dict[str, pd.DataFrame]:
    """
    Parse all FAERS tables for a given quarter.
    
    Args:
        ascii_dir: Path to the ASCII directory (e.g., ./data/raw/2026q1/ascii)
        quarter: Quarter identifier (e.g., '2026q1')
    
    Returns:
        Dictionary mapping table name → cleaned DataFrame
    """
    logger.info(f"{'='*60}")
    logger.info(f"Parsing FAERS quarter: {quarter}")
    logger.info(f"Source: {ascii_dir}")
    logger.info(f"{'='*60}")
    
    CLEANERS = {
        "DEMO": clean_demo,
        "DRUG": clean_drug,
        "REAC": clean_reac,
        "OUTC": clean_outc,
        "THER": clean_ther,
        "INDI": clean_indi,
    }
    
    tables = {}
    
    for i, (table_name, cleaner) in enumerate(CLEANERS.items()):
        if status_callback:
            progress = int(10 + (i / len(CLEANERS)) * 30)
            status_callback("Parsing", f"Parsing ASCII file: {table_name}...", progress)
            
        filepath = find_table_file(ascii_dir, table_name)
        if filepath is None:
            logger.warning(f"Skipping {table_name} — file not found")
            continue
        
        raw_df = load_raw_table(filepath, table_name)
        cleaned_df = cleaner(raw_df, quarter)
        tables[table_name] = cleaned_df
        
        logger.info(f"   {table_name}: {len(cleaned_df):,} rows cleaned")
    
    # Deduplicate DEMO (must happen after initial clean)
    if "DEMO" in tables:
        tables["DEMO"] = deduplicate_demo(tables["DEMO"])
    
    # RPSR — simple table, no special cleaning needed
    rpsr_file = find_table_file(ascii_dir, "RPSR")
    if rpsr_file:
        rpsr_df = load_raw_table(rpsr_file, "RPSR")
        rpsr_df["quarter"] = quarter
        rpsr_df["report_id"] = pd.to_numeric(rpsr_df["report_id"], errors="coerce")
        rpsr_df = rpsr_df.dropna(subset=["report_id"])
        tables["RPSR"] = rpsr_df
    
    logger.info(f"{'='*60}")
    logger.info("Parse complete. Summary:")
    for name, df in tables.items():
        logger.info(f"  {name:6s}: {len(df):>10,} rows")
    
    return tables

if __name__ == "__main__":
    import sys
    quarter = sys.argv[1] if len(sys.argv) > 1 else "2026q1"
    ascii_dir = f"./data/raw/{quarter}/ascii"
    tables = parse_quarter(ascii_dir, quarter)
    print("\nParsing complete!")
    for name, df in tables.items():
        print(f"  {name}: {len(df):,} rows | {df.memory_usage(deep=True).sum() / 1024**2:.1f} MB")
