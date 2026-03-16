"""Professional PDF inspection reports with embedded evidence imagery and OSHA analysis."""
from __future__ import annotations

import logging
from datetime import datetime
from io import BytesIO
from typing import Any

logger = logging.getLogger(__name__)

# Severity palette
SEV_HEX = {
    'critical': '#FF2D2D',
    'high':     '#FF8C00',
    'medium':   '#E8B400',
    'low':      '#22C55E',
    'unknown':  '#888888',
}
NAVY   = '#0B1E3D'
SLATE  = '#1E2D45'
LIGHT  = '#F4F6FA'
WHITE  = '#FFFFFF'
BORDER = '#CBD5E1'


def _hex(code: str):
    from reportlab.lib.colors import HexColor
    return HexColor(code)


def _fetch_image(url: str, max_w: float, max_h: float):
    """Download image from URL and return a scaled ReportLab Image, or None on failure."""
    if not url:
        return None
    try:
        import httpx
        from reportlab.platypus import Image as RLImage
        from reportlab.lib.utils import ImageReader
        resp = httpx.get(url, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        data = BytesIO(resp.content)
        reader = ImageReader(data)
        iw, ih = reader.getSize()
        scale = min(max_w / iw, max_h / ih, 1.0)
        data.seek(0)
        return RLImage(data, width=iw * scale, height=ih * scale)
    except Exception as e:
        logger.warning(f"Could not load evidence image from {url}: {e}")
        return None


class ReportPDFService:

    def __init__(self):
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.lib.colors import HexColor

        base = getSampleStyleSheet()
        TA_CENTER_ = TA_CENTER
        TA_LEFT_   = TA_LEFT

        self.styles = {
            'cover_title': ParagraphStyle(
                'CoverTitle', parent=base['Title'],
                fontSize=28, textColor=HexColor(WHITE),
                spaceAfter=8, alignment=TA_CENTER_,
                fontName='Helvetica-Bold',
            ),
            'cover_sub': ParagraphStyle(
                'CoverSub', parent=base['Normal'],
                fontSize=11, textColor=HexColor('#A8BDD4'),
                alignment=TA_CENTER_, spaceAfter=4,
            ),
            'section_heading': ParagraphStyle(
                'SectionHeading', parent=base['Heading1'],
                fontSize=14, textColor=HexColor(NAVY),
                fontName='Helvetica-Bold', spaceBefore=18, spaceAfter=8,
                borderPad=4,
            ),
            'sub_heading': ParagraphStyle(
                'SubHeading', parent=base['Heading2'],
                fontSize=11, textColor=HexColor(SLATE),
                fontName='Helvetica-Bold', spaceBefore=10, spaceAfter=4,
            ),
            'body': ParagraphStyle(
                'Body', parent=base['Normal'],
                fontSize=9, textColor=HexColor('#334155'),
                leading=14, spaceAfter=4,
            ),
            'body_small': ParagraphStyle(
                'BodySmall', parent=base['Normal'],
                fontSize=8, textColor=HexColor('#64748B'),
                leading=12,
            ),
            'violation_title': ParagraphStyle(
                'ViolationTitle', parent=base['Normal'],
                fontSize=12, fontName='Helvetica-Bold',
                textColor=HexColor(WHITE), spaceAfter=2,
            ),
            'osha_code': ParagraphStyle(
                'OshaCode', parent=base['Normal'],
                fontSize=10, fontName='Helvetica-Bold',
                textColor=HexColor(WHITE), spaceAfter=0,
            ),
            'label': ParagraphStyle(
                'Label', parent=base['Normal'],
                fontSize=8, fontName='Helvetica-Bold',
                textColor=HexColor('#475569'),
                spaceBefore=6, spaceAfter=2,
                textTransform='uppercase',
            ),
            'value': ParagraphStyle(
                'Value', parent=base['Normal'],
                fontSize=9.5, textColor=HexColor('#1E293B'),
                leading=14, spaceAfter=4,
            ),
            'remediation': ParagraphStyle(
                'Remediation', parent=base['Normal'],
                fontSize=9, textColor=HexColor('#166534'),
                backColor=HexColor('#F0FDF4'),
                borderPad=6, leading=13, spaceAfter=4,
            ),
            'annex_item': ParagraphStyle(
                'AnnexItem', parent=base['Normal'],
                fontSize=7.5, textColor=HexColor('#475569'),
                leading=11, spaceAfter=2,
            ),
            'action_item': ParagraphStyle(
                'ActionItem', parent=base['Normal'],
                fontSize=9, textColor=HexColor('#1E293B'),
                leading=14, spaceAfter=5, leftIndent=12,
            ),
        }

    # ────────────────────────────────────────────────────────────────────────
    def build_pdf(self, report: dict[str, Any]) -> bytes:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, KeepTogether, PageBreak,
        )
        from reportlab.lib.colors import HexColor

        buf = BytesIO()
        W, H = A4
        left = right = 1.8 * cm
        top = bot = 1.5 * cm

        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=left, rightMargin=right,
            topMargin=top, bottomMargin=bot,
            title=report.get('title', 'SiteGuard AI Safety Report'),
        )

        content_w = W - left - right
        story = []

        # ── COVER PAGE ────────────────────────────────────────────────────
        story += self._cover_page(report, content_w)
        story.append(PageBreak())

        # ── EXECUTIVE SUMMARY ─────────────────────────────────────────────
        story.append(self._section_rule('1. Executive Summary', content_w))
        story.append(Paragraph(
            report.get('executive_summary', 'No summary available.'),
            self.styles['body']
        ))
        story.append(Spacer(1, 10))

        # ── RISK MATRIX ───────────────────────────────────────────────────
        story.append(self._section_rule('2. Risk Assessment Matrix', content_w))
        story += self._risk_matrix(report, content_w)
        story.append(Spacer(1, 10))

        # ── VIOLATIONS DETAIL ─────────────────────────────────────────────
        violations = report.get('violations', [])
        story.append(self._section_rule(
            f'3. Detailed Violation Analysis  ({len(violations)} findings)',
            content_w
        ))

        if not violations:
            story.append(Paragraph(
                'No violations were detected in this inspection session.',
                self.styles['body']
            ))
        else:
            for i, v in enumerate(violations, 1):
                story.append(Spacer(1, 8))
                story += self._violation_block(v, i, content_w)

        story.append(Spacer(1, 12))

        # ── CORRECTIVE ACTIONS ────────────────────────────────────────────
        actions = report.get('corrective_actions', [])
        if actions:
            story.append(self._section_rule('4. Priority Corrective Actions', content_w))
            for i, action in enumerate(actions, 1):
                story.append(Paragraph(
                    f'<b>{i}.</b>  {action}',
                    self.styles['action_item']
                ))
            story.append(Spacer(1, 8))

        # ── CRITICAL FINDINGS ─────────────────────────────────────────────
        findings = report.get('critical_findings', [])
        if findings:
            story.append(self._section_rule('5. Critical Findings', content_w))
            for f in findings:
                story.append(Paragraph(f'• {f}', self.styles['body']))
            story.append(Spacer(1, 8))

        story.append(PageBreak())

        # ── OSHA ANNEX ────────────────────────────────────────────────────
        story.append(self._section_rule('Appendix A: OSHA Standards Coverage', content_w))
        story += self._annex_table(report.get('osha_annex', []), content_w)
        story.append(Spacer(1, 12))

        # ── NEBOSH ANNEX ──────────────────────────────────────────────────
        story.append(self._section_rule('Appendix B: NEBOSH Elements Coverage', content_w))
        story += self._annex_table(report.get('nebosh_annex', []), content_w)

        doc.build(story)
        return buf.getvalue()

    # ── Cover Page ────────────────────────────────────────────────────────
    def _cover_page(self, report: dict, w: float):
        from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.units import cm
        from reportlab.lib.colors import HexColor

        score = int(report.get('compliance_score', 0))
        violations = report.get('violations', [])
        sev_counts = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
        for v in violations:
            sev = v.get('severity', 'low')
            sev_counts[sev] = sev_counts.get(sev, 0) + 1

        # Header block (navy background via table)
        header_data = [
            [Paragraph('🛡 SITEGUARD AI', self.styles['cover_title'])],
            [Paragraph('Automated Safety Inspection Report', self.styles['cover_sub'])],
            [Paragraph('Powered by Gemini 3.1 Pro · OSHA &amp; NEBOSH Compliant', self.styles['cover_sub'])],
        ]
        header_table = Table(header_data, colWidths=[w])
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), HexColor(NAVY)),
            ('TOPPADDING', (0, 0), (0, 0), 24),
            ('BOTTOMPADDING', (0, -1), (-1, -1), 20),
            ('LEFTPADDING', (0, 0), (-1, -1), 16),
            ('RIGHTPADDING', (0, 0), (-1, -1), 16),
        ]))

        # Meta info
        gen_date = report.get('generated_at', '')
        if gen_date:
            try:
                dt = datetime.fromisoformat(gen_date.replace('Z', ''))
                gen_date = dt.strftime('%d %B %Y, %H:%M UTC')
            except Exception:
                pass

        meta_data = [
            ['Site / Location', report.get('site_id', '—')],
            ['Camera / Source',  report.get('camera_id', '—')],
            ['Session ID',       report.get('session_id', '—')[:16] + '…'],
            ['Report Generated', gen_date],
            ['Total Findings',   str(len(violations))],
        ]
        meta_table = Table(meta_data, colWidths=[w * 0.35, w * 0.65])
        meta_table.setStyle(TableStyle([
            ('FONTNAME',    (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE',    (0, 0), (-1, -1), 9),
            ('TEXTCOLOR',   (0, 0), (0, -1), HexColor('#64748B')),
            ('TEXTCOLOR',   (1, 0), (1, -1), HexColor('#1E293B')),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [HexColor('#F8FAFC'), HexColor(WHITE)]),
            ('TOPPADDING',  (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('GRID',        (0, 0), (-1, -1), 0.5, HexColor(BORDER)),
        ]))

        # Compliance score visual
        score_color = (
            '#FF2D2D' if score < 55 else
            '#FF8C00' if score < 70 else
            '#E8B400' if score < 85 else
            '#22C55E'
        )
        score_label = (
            'NON-COMPLIANT' if score < 55 else
            'POOR'          if score < 70 else
            'FAIR'          if score < 85 else
            'GOOD'
        )
        bar_filled = int(w * 0.6 * score / 100)
        bar_empty  = int(w * 0.6) - bar_filled

        score_rows = [
            [Paragraph(f'<b>Compliance Score</b>', self.styles['label']),
             Paragraph(f'<font size="22"><b>{score}%</b></font>', self.styles['body'])],
        ]
        score_table = Table(score_rows, colWidths=[w * 0.5, w * 0.5])
        score_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), HexColor('#EFF6FF')),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 14),
            ('GRID', (0, 0), (-1, -1), 0.5, HexColor(BORDER)),
        ]))

        # Severity summary
        sev_rows = [['Severity', 'Count', 'Status']]
        for sev in ('critical', 'high', 'medium', 'low'):
            cnt = sev_counts[sev]
            status = '⚠ Requires Immediate Action' if sev == 'critical' and cnt > 0 else (
                     '⚠ Action Required'           if sev == 'high'     and cnt > 0 else (
                     '○ Monitor'                   if sev == 'medium'   and cnt > 0 else
                     '✓ Acceptable'                if cnt == 0 else '— Review'))
            sev_rows.append([sev.upper(), str(cnt), status])

        sev_table = Table(sev_rows, colWidths=[w * 0.25, w * 0.15, w * 0.6])
        sev_table.setStyle(TableStyle([
            ('BACKGROUND',  (0, 0), (-1, 0), HexColor(SLATE)),
            ('TEXTCOLOR',   (0, 0), (-1, 0), HexColor(WHITE)),
            ('FONTNAME',    (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',    (0, 0), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor(WHITE), HexColor('#F8FAFC')]),
            ('TOPPADDING',  (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('GRID',        (0, 0), (-1, -1), 0.5, HexColor(BORDER)),
            ('TEXTCOLOR', (0, 1), (0, 1), HexColor(SEV_HEX['critical'])),
            ('TEXTCOLOR', (0, 2), (0, 2), HexColor(SEV_HEX['high'])),
            ('TEXTCOLOR', (0, 3), (0, 3), HexColor(SEV_HEX['medium'])),
            ('TEXTCOLOR', (0, 4), (0, 4), HexColor(SEV_HEX['low'])),
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ]))

        disclaimer = Paragraph(
            'This report was automatically generated by SiteGuard AI using computer vision analysis. '
            'All findings should be reviewed by a qualified safety officer before taking enforcement action. '
            'Evidence images are extracted directly from the inspected video recording.',
            self.styles['body_small']
        )

        return [
            header_table,
            Spacer(1, 16),
            meta_table,
            Spacer(1, 14),
            score_table,
            Spacer(1, 14),
            sev_table,
            Spacer(1, 20),
            disclaimer,
        ]

    # ── Section Rule ──────────────────────────────────────────────────────
    def _section_rule(self, title: str, w: float):
        from reportlab.platypus import Table, TableStyle, Paragraph
        from reportlab.lib.colors import HexColor
        t = Table([[Paragraph(title, self.styles['section_heading'])]], colWidths=[w])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), HexColor('#EFF6FF')),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LINEBELOW', (0, 0), (-1, -1), 2, HexColor(NAVY)),
        ]))
        return t

    # ── Risk Matrix ───────────────────────────────────────────────────────
    def _risk_matrix(self, report: dict, w: float):
        from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.colors import HexColor

        violations = report.get('violations', [])
        by_type: dict[str, dict] = {}
        for v in violations:
            vt = v.get('violation_type', 'unknown').replace('_', ' ').title()
            sev = v.get('severity', 'low')
            if vt not in by_type:
                by_type[vt] = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0, 'total': 0}
            by_type[vt][sev] = by_type[vt].get(sev, 0) + 1
            by_type[vt]['total'] += 1

        rows = [['Violation Category', 'Critical', 'High', 'Medium', 'Low', 'Total']]
        for cat, counts in sorted(by_type.items(), key=lambda x: -x[1]['total']):
            rows.append([
                cat,
                str(counts.get('critical', 0)) or '—',
                str(counts.get('high', 0)) or '—',
                str(counts.get('medium', 0)) or '—',
                str(counts.get('low', 0)) or '—',
                str(counts.get('total', 0)),
            ])

        if len(rows) == 1:
            return [Paragraph('No violations recorded.', self.styles['body'])]

        table = Table(rows, colWidths=[w * 0.40, w * 0.12, w * 0.12, w * 0.12, w * 0.12, w * 0.12])
        table.setStyle(TableStyle([
            ('BACKGROUND',  (0, 0), (-1, 0), HexColor(SLATE)),
            ('TEXTCOLOR',   (0, 0), (-1, 0), HexColor(WHITE)),
            ('FONTNAME',    (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',    (0, 0), (-1, -1), 8.5),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor(WHITE), HexColor('#F8FAFC')]),
            ('TOPPADDING',  (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('ALIGN',       (1, 0), (-1, -1), 'CENTER'),
            ('GRID',        (0, 0), (-1, -1), 0.5, HexColor(BORDER)),
            ('TEXTCOLOR',   (1, 1), (1, -1), HexColor(SEV_HEX['critical'])),
            ('TEXTCOLOR',   (2, 1), (2, -1), HexColor(SEV_HEX['high'])),
            ('TEXTCOLOR',   (3, 1), (3, -1), HexColor(SEV_HEX['medium'])),
            ('TEXTCOLOR',   (4, 1), (4, -1), HexColor(SEV_HEX['low'])),
            ('FONTNAME',    (1, 1), (-1, -1), 'Helvetica-Bold'),
        ]))
        return [table]

    # ── Violation Block ───────────────────────────────────────────────────
    def _violation_block(self, v: dict, idx: int, w: float):
        from reportlab.platypus import Table, TableStyle, Paragraph, Spacer, KeepTogether
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.colors import HexColor
        from reportlab.lib.units import cm

        sev  = v.get('severity', 'low').lower()
        sev_color = HexColor(SEV_HEX.get(sev, '#888888'))
        osha = v.get('osha_code', 'N/A')
        vtype = v.get('violation_type', 'Unknown').replace('_', ' ').title()
        desc  = v.get('description', '')
        remed = v.get('remediation', '')
        conf  = float(v.get('confidence', 0)) * 100
        frame = v.get('frame_number')
        ts    = v.get('timestamp_in_video')

        # Header row
        header_rows = [[
            Paragraph(f'#{idx}  {vtype.upper()}', self.styles['violation_title']),
            Paragraph(osha, self.styles['osha_code']),
        ]]
        header_tbl = Table(header_rows, colWidths=[w * 0.6, w * 0.4])
        header_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), sev_color),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ]))

        items = [header_tbl]

        # Evidence image
        img_url = v.get('annotated_image_url') or v.get('evidence_image_url')
        img_obj = _fetch_image(img_url, w, 9 * cm) if img_url else None

        detail_rows = []

        if img_obj:
            # Image + detail side by side
            detail_content = [
                Paragraph('SEVERITY LEVEL', self.styles['label']),
                Paragraph(sev.upper(), ParagraphStyle('SevLabel', parent=self.styles['label'], fontSize=10, textColor=HexColor(SEV_HEX.get(sev, '#888888')), fontName='Helvetica-Bold')),
                Spacer(1, 6),
                Paragraph('DESCRIPTION', self.styles['label']),
                Paragraph(desc, self.styles['value']),
                Spacer(1, 4),
                Paragraph('OSHA STANDARD', self.styles['label']),
                Paragraph(f'<b>{osha}</b> — {_osha_description(osha)}', self.styles['value']),
                Spacer(1, 4),
                Paragraph('REMEDIATION ACTION', self.styles['label']),
                Paragraph(remed, self.styles['remediation']),
                Spacer(1, 4),
                Paragraph('EVIDENCE METADATA', self.styles['label']),
                Paragraph(
                    f'Confidence: <b>{conf:.0f}%</b>  |  '
                    f'Frame: <b>{frame if frame else "N/A"}</b>  |  '
                    f'Timestamp: <b>{f"{int(ts // 60)}:{int(ts % 60):02d}" if ts else "N/A"}</b>',
                    self.styles['body_small']
                ),
            ]

            from reportlab.platypus import Table as RLTable, TableStyle as RLTS
            side_by_side = RLTable(
                [[img_obj, detail_content]],
                colWidths=[w * 0.5, w * 0.47],
            )
            side_by_side.setStyle(RLTS([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ('TOPPADDING', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                ('BACKGROUND', (0, 0), (-1, -1), HexColor('#FAFBFE')),
                ('BOX', (0, 0), (-1, -1), 0.5, HexColor(BORDER)),
            ]))
            items.append(side_by_side)
        else:
            # No image — show detail table full width
            rows_content = [
                [Paragraph('SEVERITY', self.styles['label']),
                 Paragraph(sev.upper(), self.styles['value'])],
                [Paragraph('DESCRIPTION', self.styles['label']),
                 Paragraph(desc, self.styles['value'])],
                [Paragraph('OSHA STANDARD', self.styles['label']),
                 Paragraph(f'<b>{osha}</b> — {_osha_description(osha)}', self.styles['value'])],
                [Paragraph('REMEDIATION', self.styles['label']),
                 Paragraph(remed, self.styles['value'])],
                [Paragraph('CONFIDENCE', self.styles['label']),
                 Paragraph(f'{conf:.0f}%  |  Frame {frame or "N/A"}', self.styles['body_small'])],
            ]
            detail_tbl = Table(rows_content, colWidths=[w * 0.20, w * 0.77])
            detail_tbl.setStyle(TableStyle([
                ('ROWBACKGROUNDS', (0, 0), (-1, -1), [HexColor(WHITE), HexColor('#F8FAFC')]),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 0.3, HexColor(BORDER)),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            items.append(detail_tbl)

        items.append(Spacer(1, 6))
        return [KeepTogether(items)]

    # ── Annex Table ───────────────────────────────────────────────────────
    def _annex_table(self, lines: list[str], w: float):
        from reportlab.platypus import Table, TableStyle, Paragraph
        from reportlab.lib.colors import HexColor

        if not lines:
            return [Paragraph('No annex data available.', self.styles['body'])]

        rows = []
        for line in lines:
            is_violated = 'Violation Observed' in line or 'Priority Action' in line
            color = HexColor('#FFF1F1') if is_violated else HexColor(WHITE)
            p = Paragraph(line, self.styles['annex_item'])
            rows.append([p, '⚠' if is_violated else '✓'])

        # Split into two columns for compactness
        half = len(rows) // 2 + len(rows) % 2
        left_rows  = rows[:half]
        right_rows = rows[half:]
        # Pad right column
        while len(right_rows) < len(left_rows):
            right_rows.append(['', ''])

        combined = []
        for l, r in zip(left_rows, right_rows):
            combined.append([l[0], l[1], r[0], r[1]])

        table = Table(combined, colWidths=[w * 0.44, w * 0.04, w * 0.44, w * 0.04])
        table.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 7.5),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.3, HexColor(BORDER)),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [HexColor(WHITE), HexColor('#F8FAFC')]),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ('ALIGN', (3, 0), (3, -1), 'CENTER'),
        ]))
        return [table]


# ── Helpers ────────────────────────────────────────────────────────────────

class ParagraphStyleProxy:
    """Dummy style for inline use — not actually used by ReportLab."""
    def __init__(self, _): pass


def _osha_description(code: str) -> str:
    """Return a brief human-readable description for common OSHA codes."""
    mapping = {
        '1926.501': 'Duty to have fall protection',
        '1926.502': 'Fall protection systems and practices',
        '1926.503': 'Fall protection training requirements',
        '1926.100': 'Head protection (hard hat)',
        '1926.102': 'Eye and face protection',
        '1926.104': 'Safety belts, lifelines, lanyards',
        '1926.403': 'General electrical equipment requirements',
        '1926.416': 'Electrical safety-related work practices',
        '1926.451': 'Scaffold requirements',
        '1926.454': 'Scaffold training requirements',
        '1926.550': 'Cranes and derricks',
        '1926.601': 'Motor vehicles',
        '1926.602': 'Material handling equipment',
        '1926.651': 'Specific excavation requirements',
        '1926.652': 'Protective systems for excavations',
        '1926.95':  'PPE — general requirements',
        '1926.25':  'Housekeeping requirements',
        '1910.132': 'PPE — general industry',
        '1910.147': 'Control of hazardous energy (lockout/tagout)',
        '1910.212': 'Machine guarding',
    }
    for key, desc in mapping.items():
        if key in code:
            return desc
    return 'Refer to OSHA 29 CFR standard'
