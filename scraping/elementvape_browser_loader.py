#!/usr/bin/env python3
"""Validate and load Element Vape records collected through Chrome MCP.

Collection is intentionally separate: run the JavaScript extractor in an
Element Vape Chrome tab and save one JSON object per line, then use this tool
to validate/review/load the staged file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SITE = "ELEMENT_VAPE"
BLOCKED_MARKERS = (
    "verify you are human", "access denied", "just a moment",
    "security check", "checking your browser", "captcha",
)


def records(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                yield line_number, None, f"invalid JSON: {error}"
                continue
            yield line_number, value, None


def validate(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["record is not an object"]
    errors = []
    url = str(value.get("url", ""))
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "www.elementvape.com":
        errors.append("url must be an https www.elementvape.com URL")
    tag = str(value.get("site_tag", "")).strip()
    expected_tag = parsed.path.rstrip("/").split("/")[-1] if parsed.path else ""
    if not tag or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag):
        errors.append("site_tag is missing or invalid")
    elif tag != expected_tag:
        errors.append("site_tag does not match URL path")
    for field in ("title", "plain_text"):
        if not str(value.get(field, "")).strip():
            errors.append(f"{field} is empty")
    if not str(value.get("html", "")).strip() and not str(value.get("rendered_html", "")).strip():
        errors.append("html/rendered_html is empty")
    # Check rendered text rather than raw HTML: legitimate third-party scripts
    # can contain strings such as "captcha" without the page being challenged.
    haystack = str(value.get("plain_text", "")).lower()
    if any(marker in haystack for marker in BLOCKED_MARKERS):
        errors.append("Cloudflare/challenge marker detected")
    price = str(value.get("price", "")).strip()
    if price and not re.fullmatch(r"\d+(?:\.\d{1,2})?", price.replace(",", "")):
        errors.append("price is not numeric")
    return errors


def normalize(value: dict) -> dict:
    price = str(value.get("price", "")).strip()
    if price:
        price = f"${float(price.replace(',', '')):.2f}"
    return {
        "title": str(value.get("title", "")).strip(),
        "link": str(value["url"]).strip(),
        "site_category": str(value.get("site_category", "browser-mcp")).strip() or "browser-mcp",
        "tag": str(value["site_tag"]).strip(),
        "sku": str(value.get("sku", "")).strip(),
        "brand": str(value.get("brand", "")).strip(),
        "html": str(value.get("html") or value.get("rendered_html") or ""),
        "plain_text": str(value["plain_text"]),
        "regular_price": price,
        "sale_price": str(value.get("sale_price", "")).strip(),
        "description": str(value.get("description", "")).strip(),
        "stock_status": str(value.get("stock_status", "")).strip(),
        "package_contents": "", "features": "", "ingredients": "",
        "warnings": "", "eliquid_contents": "", "puffs": "", "coil": "",
        "battery": "", "power_level": "", "nicotine_strength": "",
        "flavor_text": "", "reviews": [], "review_attributes": {},
        "flavor_list": [], "nicotine_strengths": [], "images": (
            [{"url": value["image_url"], "alt": value.get("title", "")}]
            if value.get("image_url") else []
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="staged JSONL from Chrome MCP")
    parser.add_argument("--load", action="store_true", help="load validated records into Azure SQL")
    parser.add_argument("--limit", type=int, default=100, help="maximum records to load")
    args = parser.parse_args()
    path = args.input if args.input.is_absolute() else ROOT / args.input
    valid, invalid, seen = [], [], set()
    for line, value, parse_error in records(path):
        errors = [parse_error] if parse_error else validate(value)
        if errors:
            invalid.append({"line": line, "errors": errors})
            continue
        assert isinstance(value, dict)
        tag = str(value["site_tag"])
        if tag in seen:
            invalid.append({"line": line, "errors": [f"duplicate site_tag: {tag}"]})
            continue
        seen.add(tag)
        valid.append(normalize(value))
    print(json.dumps({"input": str(path), "valid": len(valid), "invalid": len(invalid),
                      "invalid_examples": invalid[:20]}, indent=2))
    if not args.load:
        return 1 if invalid else 0

    if invalid:
        print("Refusing to load: fix or remove invalid records first.", file=sys.stderr)
        return 2
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    sys.path.insert(0, str(ROOT))
    from db.db_azure import connect, map_product_data, sync_ecig_product_history

    connection = connect()
    cursor = connection.cursor()
    inserted = updated = skipped = 0
    try:
        for data in valid[:args.limit]:
            cursor.execute(
                "SELECT id FROM ecig_product WHERE site_name = ? AND site_tag = ?",
                (SITE, data["tag"]),
            )
            row = cursor.fetchone()
            if row:
                # Keep updates transactional and avoid replacing fields with blanks.
                sync_ecig_product_history(row[0], data, cursor=cursor)
                assignments, params = [], []
                for field, value in (("product_name", data["title"]), ("url", data["link"]),
                                     ("brand", data["brand"]), ("html", data["html"]),
                                     ("plain_text", data["plain_text"]), ("price", data["regular_price"]),
                                     ("stock_status", data["stock_status"]), ("sku", data["sku"])):
                    if value:
                        assignments.append(f"{field} = ?")
                        params.append(value)
                if assignments:
                    cursor.execute(f"UPDATE ecig_product SET {', '.join(assignments)}, date_updated = GETDATE() WHERE id = ?",
                                   (*params, row[0]))
                    updated += 1
                else:
                    skipped += 1
            else:
                connection.commit()
                if map_product_data(SITE, data):
                    inserted += 1
            connection.commit()
        print(json.dumps({"loaded": min(len(valid), args.limit), "inserted": inserted,
                          "updated": updated, "skipped": skipped}, indent=2))
    finally:
        cursor.close()
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
