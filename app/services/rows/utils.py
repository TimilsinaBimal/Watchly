def normalize_keyword(kw: str) -> str:
    if not kw:
        return ""
    return kw.strip().replace("-", " ").replace("_", " ").title()
