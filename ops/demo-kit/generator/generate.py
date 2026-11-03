"""Make the demo kit: a quotation, a Transfer proof and an out-of-service notice.

Every name and amount in the kit is defined once, in KIT below. The generated
PDFs are committed under ops/demo-kit/files/, so serving them needs nothing
from here. Rerun after changing KIT:

  .venv/bin/python ops/demo-kit/generator/generate.py

The PDFs are text PDFs set in Be Vietnam Pro (OFL, see fonts/OFL.txt), kept
here as full TTF files because the workspace's web fonts are WOFF2 subsets.
fpdf2 is a development-only dependency. Output is deterministic: rerunning
with the same fpdf2 reproduces the same bytes.

Everything in the kit is fictional and marked as a sample on its face. The
contractor, bank and accounts do not exist; account numbers are all zeros.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONTS = HERE / "fonts"
DEFAULT_OUT = HERE.parent / "files"

SAMPLE_MARK = "MẪU — DỮ LIỆU GIẢ LẬP"


@dataclass(frozen=True)
class LineItem:
    description: str
    unit: str
    quantity: int
    unit_price_vnd: int

    @property
    def total_vnd(self) -> int:
        return self.quantity * self.unit_price_vnd


@dataclass(frozen=True)
class Kit:
    building_name: str
    building_address: str
    payer_name: str
    payer_account: str
    lift_name: str
    fault: str
    contractor_name: str
    contractor_address: str
    contractor_tax_code: str
    contractor_account: str
    bank_name: str
    quotation_number: str
    quotation_date: date
    validity_days: int
    schedule: str
    line_items: tuple[LineItem, ...]
    transfer_reference: str
    transfer_date: date

    @property
    def amount_vnd(self) -> int:
        return sum(item.total_vnd for item in self.line_items)


KIT = Kit(
    building_name="Chung cư Mẫu LamTo",
    building_address="Số 0 đường Mẫu, phường Mẫu, thành phố Mẫu",
    payer_name="Ban quản trị Chung cư Mẫu LamTo — Quỹ bảo trì",
    payer_account="0000 0000 0000",
    lift_name="Thang máy A",
    fault="Thang máy rung lắc mạnh khi chạy",
    contractor_name="Công ty TNHH Thang máy Mẫu",
    contractor_address="Số 00 phố Mẫu, phường Mẫu, thành phố Mẫu",
    contractor_tax_code="0000000000",
    contractor_account="0000 0000 0001",
    bank_name="Ngân hàng Mẫu (không có thật)",
    quotation_number="BG-MAU-0001",
    quotation_date=date(2026, 11, 2),
    validity_days=30,
    schedule="10 ngày làm việc kể từ khi Ban quản trị quyết định tiến hành",
    line_items=(
        LineItem("Khảo sát, đo rung, chẩn đoán nguyên nhân rung lắc", "lần", 1, 15_000_000),
        LineItem("Thay ray dẫn hướng cabin và đối trọng", "bộ", 1, 210_000_000),
        LineItem("Thay guốc dẫn hướng con lăn cabin", "bộ", 1, 48_000_000),
        LineItem("Thay bộ cáp tải", "bộ", 1, 165_000_000),
        LineItem("Cân chỉnh máy kéo và hệ thống phanh", "lần", 1, 62_000_000),
        LineItem("Nhân công lắp đặt, chạy thử và kiểm định an toàn", "gói", 1, 60_000_000),
    ),
    transfer_reference="GD-MAU-0001",
    transfer_date=date(2026, 11, 20),
)

QUOTATION_FILE = "bao-gia-sua-thang-may-mau.pdf"
TRANSFER_PROOF_FILE = "chung-tu-chuyen-khoan-mau.pdf"
NOTICE_FILE = "thong-bao-tam-ngung-thang-may.pdf"

# Fixed so that reruns reproduce the same bytes.
_CREATED = datetime(2026, 11, 1, tzinfo=timezone.utc)

INK = (24, 24, 32)
MUTED = (96, 96, 110)
RULE = (200, 200, 210)
SAMPLE_RED = (190, 30, 45)


# ---------------------------------------------------------------- formatting


def vnd(amount: int) -> str:
    """560000000 -> '560.000.000 ₫' style, with the Vietnamese thousands dot."""
    return f"{amount:,}".replace(",", ".")


_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]


def _three_digits(n: int, full: bool) -> str:
    hundreds, rest = divmod(n, 100)
    tens, units = divmod(rest, 10)
    words: list[str] = []
    if full or hundreds:
        words += [_DIGITS[hundreds], "trăm"]
    if tens > 1:
        words += [_DIGITS[tens], "mươi"]
        if units == 1:
            words.append("mốt")
        elif units == 4:
            words.append("tư")
        elif units == 5:
            words.append("lăm")
        elif units:
            words.append(_DIGITS[units])
    elif tens == 1:
        words.append("mười")
        if units == 5:
            words.append("lăm")
        elif units:
            words.append(_DIGITS[units])
    elif units:
        if words:
            words.append("linh")
        words.append(_DIGITS[units])
    return " ".join(words)


def vnd_in_words(amount: int) -> str:
    """Read a whole VND amount aloud in Vietnamese, as on a paper quotation."""
    if amount == 0:
        return "Không đồng"
    scales = ["", "nghìn", "triệu", "tỷ"]
    groups: list[int] = []
    while amount:
        amount, group = divmod(amount, 1000)
        groups.append(group)
    words: list[str] = []
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if not group:
            continue
        words.append(_three_digits(group, full=index != len(groups) - 1))
        if scales[index]:
            words.append(scales[index])
    text = " ".join(words) + " đồng"
    return text[0].upper() + text[1:]


def vn_date(day: date) -> str:
    return f"ngày {day.day:02d} tháng {day.month:02d} năm {day.year}"


# ---------------------------------------------------------------- documents


def _new_pdf(fmt, title: str):
    from fpdf import FPDF

    pdf = FPDF(format=fmt, unit="mm")
    pdf.set_creation_date(_CREATED)
    pdf.set_title(f"{title} ({SAMPLE_MARK})")
    pdf.set_author(SAMPLE_MARK)
    pdf.set_creator("LamTo demo kit generator")
    pdf.set_producer("LamTo demo kit generator")
    pdf.set_lang("vi")
    pdf.add_font("BVP", "", FONTS / "BeVietnamPro-Regular.ttf")
    pdf.add_font("BVP", "B", FONTS / "BeVietnamPro-Bold.ttf")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 16, 18)
    return pdf


def _watermark(pdf, size: float = 46) -> None:
    """A large diagonal sample mark across the page, under the content."""
    x, y = pdf.w / 2, pdf.h / 2
    pdf.set_font("BVP", "B", size)
    pdf.set_text_color(*SAMPLE_RED)
    with pdf.local_context(fill_opacity=0.12, stroke_opacity=0.12):
        with pdf.rotation(angle=35, x=x, y=y):
            width = pdf.get_string_width(SAMPLE_MARK)
            pdf.text(x - width / 2, y + size * 0.13, SAMPLE_MARK)
    pdf.set_text_color(*INK)


def _sample_banner(pdf) -> None:
    pdf.set_fill_color(*SAMPLE_RED)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("BVP", "B", 10)
    pdf.cell(
        0, 7, f"{SAMPLE_MARK} — tài liệu mẫu cho bản trình diễn LamTo, không có giá trị pháp lý",
        align="C", fill=True, new_x="LMARGIN", new_y="NEXT",
    )
    pdf.set_text_color(*INK)
    pdf.ln(4)


def _footer_mark(pdf) -> None:
    pdf.set_auto_page_break(auto=False)
    pdf.set_y(-14)
    pdf.set_font("BVP", "", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(
        0, 5,
        f"{SAMPLE_MARK}. Công ty, ngân hàng và số tài khoản trong tài liệu này đều không có thật.",
        align="C",
    )
    pdf.set_text_color(*INK)


def _label_value(pdf, label: str, value: str, label_width: float = 46) -> None:
    pdf.set_font("BVP", "", 10)
    pdf.set_text_color(*MUTED)
    pdf.cell(label_width, 6.5, label)
    pdf.set_text_color(*INK)
    pdf.set_font("BVP", "B", 10)
    pdf.multi_cell(0, 6.5, value, align="L", new_x="LMARGIN", new_y="NEXT")


def build_quotation(kit: Kit) -> bytes:
    pdf = _new_pdf("A4", f"Báo giá {kit.quotation_number}")
    pdf.add_page()
    _watermark(pdf, 54)
    _sample_banner(pdf)

    pdf.set_font("BVP", "B", 15)
    pdf.cell(0, 8, kit.contractor_name.upper(), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("BVP", "", 9.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, f"Địa chỉ: {kit.contractor_address}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, f"Mã số thuế: {kit.contractor_tax_code} (giả lập)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK)
    pdf.ln(2)
    pdf.set_draw_color(*RULE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)

    pdf.set_font("BVP", "B", 18)
    pdf.cell(0, 9, "BÁO GIÁ SỬA CHỮA THANG MÁY", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("BVP", "", 10)
    pdf.cell(
        0, 6, f"Số: {kit.quotation_number} — {vn_date(kit.quotation_date).capitalize()}",
        align="C", new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(5)

    _label_value(pdf, "Kính gửi:", f"Ban quản trị {kit.building_name}")
    _label_value(pdf, "Địa chỉ công trình:", kit.building_address)
    _label_value(pdf, "Thiết bị:", kit.lift_name)
    _label_value(pdf, "Hiện tượng:", f"{kit.fault}.")
    pdf.ln(4)

    widths = (12, 98, 14, 10, 40)
    headers = ("STT", "Hạng mục", "ĐVT", "SL", "Thành tiền (VND)")
    pdf.set_font("BVP", "B", 9.5)
    pdf.set_fill_color(238, 238, 244)
    for width, header in zip(widths, headers):
        pdf.cell(width, 8, header, border=1, align="C", fill=True)
    pdf.ln()
    pdf.set_font("BVP", "", 9.5)
    for number, item in enumerate(kit.line_items, start=1):
        row = (str(number), item.description, item.unit, str(item.quantity), vnd(item.total_vnd))
        aligns = ("C", "L", "C", "C", "R")
        for width, value, align in zip(widths, row, aligns):
            pdf.cell(width, 8, value, border=1, align=align)
        pdf.ln()
    pdf.set_font("BVP", "B", 10)
    pdf.cell(sum(widths[:-1]), 9, "TỔNG CỘNG (đã gồm thuế GTGT)", border=1, align="R")
    pdf.cell(widths[-1], 9, vnd(kit.amount_vnd), border=1, align="R")
    pdf.ln(11)

    pdf.set_font("BVP", "", 10)
    pdf.multi_cell(0, 6, f"Bằng chữ: {vnd_in_words(kit.amount_vnd)}.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    _label_value(pdf, "Thời gian thực hiện:", kit.schedule)
    _label_value(pdf, "Hiệu lực báo giá:", f"{kit.validity_days} ngày kể từ ngày báo giá")
    _label_value(pdf, "Bảo hành:", "12 tháng cho vật tư thay thế")
    _label_value(pdf, "Thanh toán:", f"Chuyển khoản vào tài khoản {kit.contractor_account} tại {kit.bank_name}")
    pdf.ln(10)

    pdf.set_x(pdf.w - pdf.r_margin - 80)
    pdf.set_font("BVP", "B", 10)
    pdf.cell(80, 6, f"ĐẠI DIỆN {kit.contractor_name.upper()}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(pdf.w - pdf.r_margin - 80)
    pdf.set_font("BVP", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(80, 6, "(Không có chữ ký — tài liệu mẫu)", align="C")
    pdf.set_text_color(*INK)

    _footer_mark(pdf)
    return bytes(pdf.output())


def build_transfer_proof(kit: Kit) -> bytes:
    pdf = _new_pdf("A4", f"Chứng từ chuyển khoản {kit.transfer_reference}")
    pdf.add_page()
    _watermark(pdf, 54)
    _sample_banner(pdf)

    pdf.set_font("BVP", "B", 15)
    pdf.cell(0, 8, kit.bank_name.upper(), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("BVP", "", 9.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, "Ngân hàng giả lập dùng cho bản trình diễn LamTo", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK)
    pdf.ln(2)
    pdf.set_draw_color(*RULE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)

    pdf.set_font("BVP", "B", 18)
    pdf.cell(0, 9, "CHỨNG TỪ CHUYỂN KHOẢN", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("BVP", "B", 11)
    pdf.set_text_color(*SAMPLE_RED)
    pdf.cell(0, 7, f"BẢN MẪU GIẢ LẬP — {SAMPLE_MARK}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK)
    pdf.ln(6)

    _label_value(pdf, "Số giao dịch:", f"{kit.transfer_reference} (giả lập)", 58)
    _label_value(pdf, "Ngày giao dịch:", vn_date(kit.transfer_date).capitalize(), 58)
    _label_value(pdf, "Trạng thái:", "Thành công (giả lập)", 58)
    pdf.ln(3)
    _label_value(pdf, "Tài khoản chuyển:", f"{kit.payer_account} (số tài khoản giả)", 58)
    _label_value(pdf, "Chủ tài khoản chuyển:", kit.payer_name, 58)
    pdf.ln(3)
    _label_value(pdf, "Tài khoản nhận:", f"{kit.contractor_account} (số tài khoản giả)", 58)
    _label_value(pdf, "Chủ tài khoản nhận:", kit.contractor_name, 58)
    _label_value(pdf, "Ngân hàng nhận:", kit.bank_name, 58)
    pdf.ln(3)
    _label_value(pdf, "Số tiền:", f"{vnd(kit.amount_vnd)} VND", 58)
    _label_value(pdf, "Bằng chữ:", vnd_in_words(kit.amount_vnd), 58)
    _label_value(pdf, "Phí giao dịch:", "0 VND", 58)
    _label_value(
        pdf, "Nội dung:",
        f"Thanh toán báo giá {kit.quotation_number} sửa chữa {kit.lift_name}, {kit.building_name}",
        58,
    )
    pdf.ln(10)

    pdf.set_draw_color(*SAMPLE_RED)
    pdf.set_line_width(0.6)
    pdf.set_text_color(*SAMPLE_RED)
    pdf.set_font("BVP", "B", 10)
    pdf.multi_cell(
        0, 6.5,
        "Chứng từ này là bản mẫu giả lập. Không có giao dịch nào được thực hiện "
        "và không có tài khoản ngân hàng nào trong chứng từ là thật.",
        border=1, align="C", padding=3, new_x="LMARGIN", new_y="NEXT",
    )
    pdf.set_text_color(*INK)

    _footer_mark(pdf)
    return bytes(pdf.output())


def build_notice(kit: Kit) -> bytes:
    """An A5 out-of-service notice, high contrast so a phone photographs it well."""
    pdf = _new_pdf((148, 210), "Thông báo thang máy tạm ngừng hoạt động")
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(12, 12, 12)
    pdf.add_page()

    # A thick frame, the way a taped notice reads from across a lift car.
    pdf.set_draw_color(*INK)
    pdf.set_line_width(2.2)
    pdf.rect(8, 8, pdf.w - 16, pdf.h - 16)

    pdf.set_y(18)
    pdf.set_fill_color(*SAMPLE_RED)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("BVP", "B", 30)
    pdf.cell(0, 18, "TẠM NGỪNG", align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 16, "HOẠT ĐỘNG", align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK)
    pdf.ln(8)

    pdf.set_font("BVP", "B", 22)
    pdf.cell(0, 11, kit.lift_name.upper(), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("BVP", "", 15)
    pdf.multi_cell(0, 8, f"{kit.fault}.", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.multi_cell(
        0, 8, "Vui lòng đi thang máy khác\nhoặc thang bộ.\nĐã báo Ban quản lý.",
        align="C", new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(6)
    pdf.set_font("BVP", "", 11)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, kit.building_name, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "Xin lỗi cư dân vì sự bất tiện.", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_y(pdf.h - 26)
    pdf.set_text_color(*SAMPLE_RED)
    pdf.set_font("BVP", "B", 12)
    pdf.cell(0, 7, SAMPLE_MARK, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("BVP", "", 8.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, "Đạo cụ cho bản trình diễn LamTo", align="C")
    pdf.set_text_color(*INK)
    return bytes(pdf.output())


def build_all(kit: Kit = KIT) -> dict[str, bytes]:
    return {
        QUOTATION_FILE: build_quotation(kit),
        TRANSFER_PROOF_FILE: build_transfer_proof(kit),
        NOTICE_FILE: build_notice(kit),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, data in build_all().items():
        (args.out / name).write_bytes(data)
        print(f"{args.out / name}  {len(data):,} bytes")


if __name__ == "__main__":
    main()
