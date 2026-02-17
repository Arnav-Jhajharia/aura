/**
 * WhatsApp Business API — Message Template Reference
 * ===================================================
 *
 * This file generates a .docx reference document covering:
 * 1. Template Management API (create, read, update, delete templates programmatically)
 * 2. Template Sending API (send approved templates to users)
 * 3. Donna-specific templates and integration architecture
 * 4. The 24-hour window routing logic
 *
 * Official docs: https://developers.facebook.com/docs/whatsapp/business-management-api/message-templates
 */

const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, LevelFormat, PageNumber, PageBreak, ExternalHyperlink,
  TabStopType, TabStopPosition,
} = require("docx");

// ── Layout constants ────────────────────────────────────────────
const PAGE_WIDTH = 12240;
const MARGINS = { top: 1440, right: 1440, bottom: 1440, left: 1440 };
const CONTENT_WIDTH = PAGE_WIDTH - MARGINS.left - MARGINS.right; // 9360

// ── Helpers ─────────────────────────────────────────────────────
const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 80, bottom: 80, left: 120, right: 120 };
const noBorder = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const noBorders = { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder };

function heading(text, level = HeadingLevel.HEADING_1) {
  return new Paragraph({ heading: level, children: [new TextRun({ text, bold: true })] });
}

function para(text, opts = {}) {
  return new Paragraph({
    spacing: { after: 120 },
    ...opts,
    children: [new TextRun({ text, size: 22, font: "Arial", ...opts.run })],
  });
}

function boldPara(label, text) {
  return new Paragraph({
    spacing: { after: 120 },
    children: [
      new TextRun({ text: label, bold: true, size: 22, font: "Arial" }),
      new TextRun({ text, size: 22, font: "Arial" }),
    ],
  });
}

function code(text) {
  return new Paragraph({
    spacing: { after: 80, before: 80 },
    indent: { left: 360 },
    children: [new TextRun({ text, font: "Courier New", size: 18, color: "2d2d2d" })],
    shading: { fill: "F5F5F5", type: ShadingType.CLEAR },
  });
}

function codeBlock(lines) {
  return lines.map(line =>
    new Paragraph({
      spacing: { after: 0, before: 0, line: 276 },
      indent: { left: 360 },
      shading: { fill: "F5F5F5", type: ShadingType.CLEAR },
      children: [new TextRun({ text: line, font: "Courier New", size: 17, color: "2d2d2d" })],
    })
  );
}

function tableRow(cells, headerRow = false) {
  const colWidth = Math.floor(CONTENT_WIDTH / cells.length);
  return new TableRow({
    children: cells.map(text =>
      new TableCell({
        borders,
        width: { size: colWidth, type: WidthType.DXA },
        margins: cellMargins,
        shading: headerRow ? { fill: "1a1a2e", type: ShadingType.CLEAR } : undefined,
        children: [new Paragraph({
          children: [new TextRun({
            text,
            size: 20,
            font: "Arial",
            bold: headerRow,
            color: headerRow ? "FFFFFF" : "1e1e1e",
          })],
        })],
      })
    ),
  });
}

function simpleTable(headers, rows) {
  const colWidth = Math.floor(CONTENT_WIDTH / headers.length);
  return new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: headers.map(() => colWidth),
    rows: [
      tableRow(headers, true),
      ...rows.map(row => tableRow(row)),
    ],
  });
}

function spacer() {
  return new Paragraph({ spacing: { after: 200 }, children: [] });
}

function divider() {
  return new Paragraph({
    spacing: { before: 200, after: 200 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "DDDDDD", space: 1 } },
    children: [],
  });
}

function link(text, url) {
  return new ExternalHyperlink({
    children: [new TextRun({ text, style: "Hyperlink", size: 22, font: "Arial" })],
    link: url,
  });
}

// ── Document ────────────────────────────────────────────────────
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: "1a1a2e" },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: "16213e" },
        paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 1 },
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: "0f3460" },
        paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 2 },
      },
    ],
  },
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }],
      },
      {
        reference: "numbers",
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }],
      },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: PAGE_WIDTH, height: 15840 },
        margin: MARGINS,
      },
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          children: [
            new TextRun({ text: "Aura / Donna", font: "Arial", size: 18, color: "888888" }),
            new TextRun({ text: "\tWhatsApp Template API Reference", font: "Arial", size: 18, color: "888888" }),
          ],
          tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "DDDDDD", space: 1 } },
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: "Page ", size: 18, color: "888888" }),
            new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "888888" }),
          ],
        })],
      }),
    },
    children: [

      // ════════════════════════════════════════════════════════════
      // TITLE PAGE
      // ════════════════════════════════════════════════════════════
      spacer(), spacer(), spacer(), spacer(),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 120 },
        children: [new TextRun({ text: "WhatsApp Business API", size: 48, bold: true, font: "Arial", color: "1a1a2e" })],
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 80 },
        children: [new TextRun({ text: "Message Template Reference", size: 40, bold: true, font: "Arial", color: "0f3460" })],
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 300 },
        children: [new TextRun({ text: "For Donna Proactive Messaging System", size: 24, font: "Arial", color: "666666" })],
      }),
      divider(),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 80 },
        children: [new TextRun({ text: "Covers: Template CRUD API, Sending API, 24-Hour Window Routing, Donna Integration", size: 20, font: "Arial", color: "888888" })],
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "Meta Graph API v18.0+  |  WhatsApp Cloud API", size: 20, font: "Arial", color: "888888" })],
      }),

      new PageBreak(),

      // ════════════════════════════════════════════════════════════
      // SECTION 1: THE 24-HOUR WINDOW PROBLEM
      // ════════════════════════════════════════════════════════════
      heading("1. The 24-Hour Window Problem"),
      para("WhatsApp enforces a strict messaging policy. After a user sends you a message, you have a 24-hour customer service window during which you can send any message type (text, interactive buttons, lists, media). Outside this window, you can ONLY send pre-approved template messages."),
      spacer(),
      para("This is architecturally critical for Donna. Proactive messages (deadline reminders, grade alerts, schedule nudges) often target users who haven't chatted recently. Without template messages, those proactive messages silently fail."),
      spacer(),

      simpleTable(
        ["Scenario", "Window Status", "What You Can Send"],
        [
          ["User messaged 2 hours ago", "OPEN (within 24h)", "Freeform text, buttons, lists, media"],
          ["User messaged 30 hours ago", "CLOSED (outside 24h)", "Only approved template messages"],
          ["User never messaged", "NEVER OPENED", "Only approved template messages"],
          ["Donna sends proactive msg, user replies", "RE-OPENED for 24h", "Freeform text again"],
        ]
      ),
      spacer(),

      boldPara("Key insight: ", "Template messages are the gateway. A well-crafted template that gets a reply from the user re-opens the 24-hour window, allowing Donna to follow up with her full freeform personality."),

      new PageBreak(),

      // ════════════════════════════════════════════════════════════
      // SECTION 2: TEMPLATE MANAGEMENT API
      // ════════════════════════════════════════════════════════════
      heading("2. Template Management API (CRUD)"),
      para("Templates are created, read, updated, and deleted via the WhatsApp Business Management API. The base URL is the Meta Graph API. All requests require a System User access token with whatsapp_business_management permission."),

      heading("2.1 Create a Template", HeadingLevel.HEADING_2),
      boldPara("Endpoint: ", "POST https://graph.facebook.com/v18.0/{WABA_ID}/message_templates"),
      spacer(),
      boldPara("Required fields:", ""),
      ...["name (string) \u2014 lowercase alphanumeric + underscores only, max 512 chars",
          "language (string) \u2014 BCP 47 language code, e.g. \"en\" or \"en_US\"",
          "category (enum) \u2014 UTILITY | MARKETING | AUTHENTICATION",
          "components (array) \u2014 defines HEADER, BODY, FOOTER, and BUTTONS",
      ].map(item => new Paragraph({
        numbering: { reference: "bullets", level: 0 },
        spacing: { after: 60 },
        children: [new TextRun({ text: item, size: 22, font: "Arial" })],
      })),
      spacer(),

      boldPara("Example \u2014 Create a utility template (Python):", ""),
      ...codeBlock([
        `import httpx`,
        `from config import settings`,
        ``,
        `WA_API = "https://graph.facebook.com/v18.0"`,
        ``,
        `async def create_template(name: str, body_text: str, example_values: list[str]):`,
        `    """Create a utility template programmatically."""`,
        `    async with httpx.AsyncClient() as client:`,
        `        resp = await client.post(`,
        `            f"{WA_API}/{settings.whatsapp_business_account_id}/message_templates",`,
        `            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},`,
        `            json={`,
        `                "name": name,`,
        `                "language": "en",`,
        `                "category": "UTILITY",`,
        `                "components": [`,
        `                    {`,
        `                        "type": "BODY",`,
        `                        "text": body_text,`,
        `                        "example": {`,
        `                            "body_text": [example_values]`,
        `                        }`,
        `                    }`,
        `                ]`,
        `            },`,
        `        )`,
        `        return resp.json()`,
      ]),
      spacer(),

      boldPara("Example \u2014 Create a template with header and buttons:", ""),
      ...codeBlock([
        `async def create_rich_template():`,
        `    payload = {`,
        `        "name": "deadline_reminder_v2",`,
        `        "language": "en",`,
        `        "category": "UTILITY",`,
        `        "components": [`,
        `            {`,
        `                "type": "HEADER",`,
        `                "format": "TEXT",`,
        `                "text": "Deadline Approaching"`,
        `            },`,
        `            {`,
        `                "type": "BODY",`,
        `                "text": "{{1}} is due {{2}}. {{3}}",`,
        `                "example": {`,
        `                    "body_text": [["CS2030S Lab 4", "tomorrow at 11:59 PM",`,
        `                                   "You usually start these the evening before."]]`,
        `                }`,
        `            },`,
        `            {`,
        `                "type": "FOOTER",`,
        `                "text": "Donna \u2014 your personal assistant"`,
        `            },`,
        `            {`,
        `                "type": "BUTTONS",`,
        `                "buttons": [`,
        `                    {"type": "QUICK_REPLY", "text": "Got it"},`,
        `                    {"type": "QUICK_REPLY", "text": "Remind me later"}`,
        `                ]`,
        `            }`,
        `        ]`,
        `    }`,
        `    # ... POST to API`,
      ]),
      spacer(),

      boldPara("Response (success):", ""),
      ...codeBlock([
        `{`,
        `  "id": "594425479261596",`,
        `  "status": "PENDING",`,
        `  "category": "UTILITY"`,
        `}`,
      ]),
      spacer(),

      heading("2.2 Check Template Status", HeadingLevel.HEADING_2),
      boldPara("Endpoint: ", "GET https://graph.facebook.com/v18.0/{WABA_ID}/message_templates"),
      spacer(),
      ...codeBlock([
        `async def get_templates(status: str = None):`,
        `    """List all templates, optionally filtered by status."""`,
        `    params = {}`,
        `    if status:`,
        `        params["status"] = status  # APPROVED, PENDING, REJECTED`,
        `    async with httpx.AsyncClient() as client:`,
        `        resp = await client.get(`,
        `            f"{WA_API}/{settings.whatsapp_business_account_id}/message_templates",`,
        `            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},`,
        `            params=params,`,
        `        )`,
        `        return resp.json()`,
      ]),
      spacer(),

      simpleTable(
        ["Status", "Meaning", "Can Send?"],
        [
          ["APPROVED", "Meta reviewed and approved", "Yes"],
          ["PENDING", "Submitted, awaiting review (24-48h)", "No"],
          ["REJECTED", "Failed review \u2014 check rejection reason", "No"],
          ["PAUSED", "Meta paused due to quality issues", "No"],
          ["DISABLED", "Permanently disabled", "No"],
        ]
      ),
      spacer(),

      heading("2.3 Update a Template", HeadingLevel.HEADING_2),
      boldPara("Endpoint: ", "POST https://graph.facebook.com/v18.0/{TEMPLATE_ID}"),
      para("You can only edit templates that are in APPROVED, REJECTED, or PAUSED status. Edits are limited to once per day, up to 10 times per month. Editing an approved template re-triggers review."),
      spacer(),

      heading("2.4 Delete a Template", HeadingLevel.HEADING_2),
      boldPara("Endpoint: ", "DELETE https://graph.facebook.com/v18.0/{WABA_ID}/message_templates?name={name}"),
      para("Deletes all language versions of the named template. Template names cannot be reused after deletion."),

      new PageBreak(),

      // ════════════════════════════════════════════════════════════
      // SECTION 3: SENDING TEMPLATE MESSAGES
      // ════════════════════════════════════════════════════════════
      heading("3. Sending Template Messages"),
      boldPara("Endpoint: ", "POST https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"),
      spacer(),
      para("This is the same endpoint used for sending regular messages, but with type: \"template\" instead of type: \"text\". Only APPROVED templates can be sent."),
      spacer(),

      boldPara("Example \u2014 Send a template with parameters (Python):", ""),
      ...codeBlock([
        `async def send_template(to: str, template_name: str, params: list[str]):`,
        `    """Send a pre-approved template message."""`,
        `    async with httpx.AsyncClient() as client:`,
        `        resp = await client.post(`,
        `            f"{WA_API}/{settings.whatsapp_phone_number_id}/messages",`,
        `            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},`,
        `            json={`,
        `                "messaging_product": "whatsapp",`,
        `                "to": to,`,
        `                "type": "template",`,
        `                "template": {`,
        `                    "name": template_name,`,
        `                    "language": {"code": "en"},`,
        `                    "components": [`,
        `                        {`,
        `                            "type": "body",`,
        `                            "parameters": [`,
        `                                {"type": "text", "text": p}`,
        `                                for p in params`,
        `                            ]`,
        `                        }`,
        `                    ]`,
        `                }`,
        `            },`,
        `        )`,
        `        return resp.json()`,
      ]),
      spacer(),

      boldPara("Template with quick reply buttons:", ""),
      ...codeBlock([
        `async def send_template_with_buttons(to, template_name, body_params, button_payloads):`,
        `    """Send template with quick reply buttons."""`,
        `    components = [`,
        `        {`,
        `            "type": "body",`,
        `            "parameters": [{"type": "text", "text": p} for p in body_params]`,
        `        }`,
        `    ]`,
        `    for i, payload in enumerate(button_payloads):`,
        `        components.append({`,
        `            "type": "button",`,
        `            "sub_type": "quick_reply",`,
        `            "index": str(i),`,
        `            "parameters": [{"type": "payload", "payload": payload}]`,
        `        })`,
        `    # ... POST to messages endpoint with template type`,
      ]),
      spacer(),

      heading("3.1 Component Parameter Types", HeadingLevel.HEADING_2),
      simpleTable(
        ["Component", "Parameter Type", "Notes"],
        [
          ["HEADER (text)", "{\"type\": \"text\", \"text\": \"value\"}", "Max 60 chars"],
          ["HEADER (image)", "{\"type\": \"image\", \"image\": {\"link\": \"url\"}}", "Or use media ID"],
          ["HEADER (document)", "{\"type\": \"document\", \"document\": {\"link\": \"url\"}}", "PDF, etc."],
          ["BODY", "{\"type\": \"text\", \"text\": \"value\"}", "Replaces {{1}}, {{2}}, etc."],
          ["BUTTON (quick_reply)", "{\"type\": \"payload\", \"payload\": \"data\"}", "Returned on tap"],
          ["BUTTON (url)", "{\"type\": \"text\", \"text\": \"suffix\"}", "Appended to base URL"],
        ]
      ),

      new PageBreak(),

      // ════════════════════════════════════════════════════════════
      // SECTION 4: DONNA'S TEMPLATE SET
      // ════════════════════════════════════════════════════════════
      heading("4. Donna\u2019s Recommended Templates"),
      para("These templates cover Donna's proactive messaging categories. Each should be registered once (via API or Business Manager), then reused at runtime by the proactive sender."),
      spacer(),

      simpleTable(
        ["Template Name", "Category", "Body Text", "Variables"],
        [
          ["donna_deadline", "UTILITY", "Heads up \u2014 {{1}} is due {{2}}. {{3}}", "assignment, time, context"],
          ["donna_grade_alert", "UTILITY", "New grade posted for {{1}}: {{2}}. {{3}}", "course, score, context"],
          ["donna_schedule", "UTILITY", "Coming up: {{1}} at {{2}}. {{3}}", "event, time, note"],
          ["donna_daily_digest", "UTILITY", "Your day: {{1}}", "formatted schedule"],
          ["donna_study_nudge", "UTILITY", "You have free time {{1}}. {{2}}", "time window, suggestion"],
          ["donna_email_alert", "UTILITY", "{{1}} emails worth checking. {{2}}", "count, summary"],
          ["donna_general", "UTILITY", "{{1}}", "short message"],
          ["donna_check_in", "UTILITY", "{{1}} {{2}}", "greeting, context"],
        ]
      ),
      spacer(),

      boldPara("Important constraints:", ""),
      ...["Template body max: 1,024 characters",
          "Each variable ({{1}}, {{2}}, etc.) replaces at send time",
          "You must provide example values when creating the template",
          "donna_general with a single {{1}} is risky \u2014 Meta may reject as too open-ended",
          "Quick reply buttons (\"Got it\", \"Remind later\") help re-open the 24h window",
          "Max 250 template names per WhatsApp Business Account",
          "Template names cannot be reused after deletion",
      ].map(item => new Paragraph({
        numbering: { reference: "bullets", level: 0 },
        spacing: { after: 60 },
        children: [new TextRun({ text: item, size: 22, font: "Arial" })],
      })),
      spacer(),

      boldPara("Registration script \u2014 run once to create all Donna templates:", ""),
      ...codeBlock([
        `"""scripts/register_templates.py \u2014 Register Donna's WhatsApp templates."""`,
        `import asyncio`,
        `import httpx`,
        `from config import settings`,
        ``,
        `WA_API = "https://graph.facebook.com/v18.0"`,
        ``,
        `DONNA_TEMPLATES = [`,
        `    {`,
        `        "name": "donna_deadline",`,
        `        "category": "UTILITY",`,
        `        "components": [`,
        `            {`,
        `                "type": "BODY",`,
        `                "text": "Heads up \u2014 {{1}} is due {{2}}. {{3}}",`,
        `                "example": {"body_text": [["CS2030S Lab 4", "tomorrow 11:59 PM",`,
        `                    "Here's the link."]]}`,
        `            },`,
        `            {`,
        `                "type": "BUTTONS",`,
        `                "buttons": [`,
        `                    {"type": "QUICK_REPLY", "text": "Got it"},`,
        `                    {"type": "QUICK_REPLY", "text": "Remind me later"},`,
        `                ]`,
        `            }`,
        `        ]`,
        `    },`,
        `    {`,
        `        "name": "donna_grade_alert",`,
        `        "category": "UTILITY",`,
        `        "components": [`,
        `            {`,
        `                "type": "BODY",`,
        `                "text": "New grade posted for {{1}}: {{2}}. {{3}}",`,
        `                "example": {"body_text": [["CS2030S Midterm", "78/100",`,
        `                    "Class median: 72."]]}`,
        `            }`,
        `        ]`,
        `    },`,
        `    {`,
        `        "name": "donna_schedule",`,
        `        "category": "UTILITY",`,
        `        "components": [`,
        `            {`,
        `                "type": "BODY",`,
        `                "text": "Coming up: {{1}} at {{2}}. {{3}}",`,
        `                "example": {"body_text": [["CS2103T Lecture", "2:00 PM COM1-B103",`,
        `                    "Topic: Design Patterns."]]}`,
        `            }`,
        `        ]`,
        `    },`,
        `    {`,
        `        "name": "donna_daily_digest",`,
        `        "category": "UTILITY",`,
        `        "components": [`,
        `            {`,
        `                "type": "BODY",`,
        `                "text": "Your day: {{1}}",`,
        `                "example": {"body_text": [["CS2030S lab 2pm, MA1521 tut 4pm.` +
        ` EE2026 due in 3 days."]]}`,
        `            },`,
        `            {`,
        `                "type": "BUTTONS",`,
        `                "buttons": [`,
        `                    {"type": "QUICK_REPLY", "text": "Thanks"},`,
        `                    {"type": "QUICK_REPLY", "text": "Tell me more"},`,
        `                ]`,
        `            }`,
        `        ]`,
        `    },`,
        `    {`,
        `        "name": "donna_study_nudge",`,
        `        "category": "UTILITY",`,
        `        "components": [`,
        `            {`,
        `                "type": "BODY",`,
        `                "text": "You have free time {{1}}. {{2}}",`,
        `                "example": {"body_text": [["between 2\u20134 PM",`,
        `                    "CS2103T iP increment due Friday."]]}`,
        `            }`,
        `        ]`,
        `    },`,
        `    {`,
        `        "name": "donna_email_alert",`,
        `        "category": "UTILITY",`,
        `        "components": [`,
        `            {`,
        `                "type": "BODY",`,
        `                "text": "{{1}} emails worth checking. {{2}}",`,
        `                "example": {"body_text": [["3 new", "Prof Lee replied about project."]]}`,
        `            }`,
        `        ]`,
        `    },`,
        `    {`,
        `        "name": "donna_check_in",`,
        `        "category": "UTILITY",`,
        `        "components": [`,
        `            {`,
        `                "type": "BODY",`,
        `                "text": "{{1}} {{2}}",`,
        `                "example": {"body_text": [["Good morning.",`,
        `                    "2 deadlines this week \u2014 want a game plan?"]]}`,
        `            },`,
        `            {`,
        `                "type": "BUTTONS",`,
        `                "buttons": [`,
        `                    {"type": "QUICK_REPLY", "text": "Yes"},`,
        `                    {"type": "QUICK_REPLY", "text": "Not now"},`,
        `                ]`,
        `            }`,
        `        ]`,
        `    },`,
        `]`,
        ``,
        `async def register_all():`,
        `    async with httpx.AsyncClient() as client:`,
        `        for tmpl in DONNA_TEMPLATES:`,
        `            resp = await client.post(`,
        `                f"{WA_API}/{settings.whatsapp_business_account_id}/message_templates",`,
        `                headers={"Authorization": f"Bearer {settings.whatsapp_token}"},`,
        `                json={"language": "en", **tmpl},`,
        `            )`,
        `            data = resp.json()`,
        `            status = "OK" if "id" in data else "FAILED"`,
        `            print(f"  {status}: {tmpl['name']} \u2014 {data}")`,
        ``,
        `if __name__ == "__main__":`,
        `    asyncio.run(register_all())`,
      ]),

      new PageBreak(),

      // ════════════════════════════════════════════════════════════
      // SECTION 5: 24-HOUR WINDOW ROUTING
      // ════════════════════════════════════════════════════════════
      heading("5. 24-Hour Window Routing Logic"),
      para("The proactive sender must check whether the user is inside the 24-hour conversation window before choosing the delivery method. This is the core architectural change needed in donna/brain/sender.py."),
      spacer(),

      boldPara("Updated sender with window-aware routing:", ""),
      ...codeBlock([
        `"""donna/brain/sender.py \u2014 Window-aware proactive message delivery."""`,
        ``,
        `from datetime import datetime, timedelta, timezone`,
        `from sqlalchemy import select`,
        ``,
        `from db.models import ChatMessage, User, generate_uuid`,
        `from db.session import async_session`,
        `from tools.whatsapp import send_whatsapp_message, send_whatsapp_template`,
        ``,
        `# Map Donna candidate categories \u2192 template names`,
        `CATEGORY_TEMPLATE_MAP = {`,
        `    "deadline_warning": "donna_deadline",`,
        `    "schedule_info":    "donna_schedule",`,
        `    "task_reminder":    "donna_deadline",`,
        `    "wellbeing":        "donna_check_in",`,
        `    "social":           "donna_check_in",`,
        `    "nudge":            "donna_study_nudge",`,
        `    "briefing":         "donna_daily_digest",`,
        `    "memory_recall":    "donna_check_in",`,
        `}`,
        ``,
        ``,
        `async def _is_window_open(user_id: str) -> bool:`,
        `    """Check if user messaged within the last 24 hours."""`,
        `    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)`,
        `    async with async_session() as session:`,
        `        result = await session.execute(`,
        `            select(ChatMessage.created_at)`,
        `            .where(`,
        `                ChatMessage.user_id == user_id,`,
        `                ChatMessage.role == "user",`,
        `                ChatMessage.created_at >= cutoff,`,
        `            )`,
        `            .order_by(ChatMessage.created_at.desc())`,
        `            .limit(1)`,
        `        )`,
        `        return result.scalar_one_or_none() is not None`,
        ``,
        ``,
        `async def _extract_template_params(candidate: dict) -> list[str]:`,
        `    """Extract variable values from a candidate message for template slots."""`,
        `    msg = candidate["message"]`,
        `    # Split into chunks that fit template variables`,
        `    # For donna_check_in (2 vars): first sentence + rest`,
        `    parts = msg.split(". ", 1)`,
        `    if len(parts) == 1:`,
        `        parts = [msg, ""]`,
        `    return [p.strip() for p in parts if p.strip()] or [msg]`,
        ``,
        ``,
        `async def send_proactive_message(user_id: str, candidate: dict) -> bool:`,
        `    """Send a proactive message, routing through template if outside 24h window."""`,
        `    async with async_session() as session:`,
        `        user = (await session.execute(`,
        `            select(User).where(User.id == user_id)`,
        `        )).scalar_one_or_none()`,
        ``,
        `    if not user or not user.phone:`,
        `        return False`,
        ``,
        `    message_text = candidate["message"]`,
        `    window_open = await _is_window_open(user_id)`,
        ``,
        `    try:`,
        `        if window_open:`,
        `            # Inside 24h window \u2014 send freeform Donna-voice message`,
        `            await send_whatsapp_message(to=user.phone, text=message_text)`,
        `        else:`,
        `            # Outside window \u2014 must use approved template`,
        `            category = candidate.get("category", "nudge")`,
        `            template_name = CATEGORY_TEMPLATE_MAP.get(category, "donna_check_in")`,
        `            params = await _extract_template_params(candidate)`,
        `            await send_whatsapp_template(`,
        `                to=user.phone,`,
        `                template_name=template_name,`,
        `                params=params,`,
        `            )`,
        `    except Exception:`,
        `        logger.exception("Failed to send proactive message to %s", user.phone)`,
        `        return False`,
        ``,
        `    # Persist as assistant message in chat history`,
        `    async with async_session() as session:`,
        `        session.add(ChatMessage(`,
        `            id=generate_uuid(),`,
        `            user_id=user_id,`,
        `            role="assistant",`,
        `            content=message_text,`,
        `        ))`,
        `        await session.commit()`,
        ``,
        `    return True`,
      ]),

      new PageBreak(),

      // ════════════════════════════════════════════════════════════
      // SECTION 6: PRICING
      // ════════════════════════════════════════════════════════════
      heading("6. Pricing (as of July 2025)"),
      para("WhatsApp introduced per-message pricing that varies by category and whether a conversation window is already open."),
      spacer(),

      simpleTable(
        ["Scenario", "Cost"],
        [
          ["Utility template within open 24h window", "FREE"],
          ["Utility template outside 24h window", "$0.004 \u2013 $0.046 per message (varies by country)"],
          ["Marketing template", "$0.014 \u2013 $0.069 per message"],
          ["Authentication template", "$0.003 \u2013 $0.045 per message"],
          ["Service conversation (user-initiated, within 24h)", "FREE (first 1,000/month)"],
        ]
      ),
      spacer(),

      boldPara("Cost optimization strategy: ", "Donna's goal should be to keep users inside the 24-hour window as much as possible. Every template with quick reply buttons is designed to elicit a response, which re-opens the free window. If Donna is valuable enough that students reply once a day, template costs approach zero."),

      new PageBreak(),

      // ════════════════════════════════════════════════════════════
      // SECTION 7: RATE LIMITS & SCALING
      // ════════════════════════════════════════════════════════════
      heading("7. Rate Limits and Scaling"),
      spacer(),

      simpleTable(
        ["Limit", "Value", "Notes"],
        [
          ["Messages per second", "80 msgs/sec (Cloud API)", "Per phone number ID"],
          ["Template creation", "100 per hour", "Per WABA"],
          ["Max templates", "250 names per WABA", "Each name can have multiple languages"],
          ["Messaging tier (unverified)", "250 unique users / 24h", "Rolling window"],
          ["Messaging tier 1 (verified)", "1,000 unique users / 24h", "After business verification"],
          ["Messaging tier 2", "10,000 unique users / 24h", "Based on quality rating"],
          ["Messaging tier 3", "100,000 unique users / 24h", "Based on quality rating"],
          ["Unlimited tier", "No limit", "High quality + volume history"],
        ]
      ),
      spacer(),

      boldPara("Quality rating: ", "Meta assigns a quality rating (Green/Yellow/Red) based on user feedback. If users block your number or report messages as spam, your rating drops. A Red rating can get your account restricted. This is why Donna's score_and_filter rules (daily caps, quiet hours, cooldowns) are not just UX decisions \u2014 they protect your WhatsApp account health."),

      new PageBreak(),

      // ════════════════════════════════════════════════════════════
      // SECTION 8: REQUIRED CONFIG
      // ════════════════════════════════════════════════════════════
      heading("8. Required Configuration"),
      para("Add these to your .env and config.py to support template management:"),
      spacer(),

      ...codeBlock([
        `# .env additions`,
        `WHATSAPP_BUSINESS_ACCOUNT_ID=123456789012345  # WABA ID (different from phone number ID)`,
        ``,
        `# The WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID you already have`,
        `# are sufficient for sending. The WABA_ID is only needed for`,
        `# template management (create/read/update/delete).`,
      ]),
      spacer(),

      ...codeBlock([
        `# config.py addition`,
        `class Settings(BaseSettings):`,
        `    # ... existing fields ...`,
        `    whatsapp_business_account_id: str = ""  # For template management API`,
      ]),
      spacer(),

      heading("8.1 Where to find your WABA ID", HeadingLevel.HEADING_2),
      ...["Go to Meta Business Suite \u2192 business.facebook.com",
          "Navigate to Settings \u2192 Business Settings \u2192 Accounts \u2192 WhatsApp Accounts",
          "Your WABA ID is displayed there (numeric, ~15 digits)",
          "This is NOT the same as your Phone Number ID (which you already have)",
      ].map(item => new Paragraph({
        numbering: { reference: "numbers", level: 0 },
        spacing: { after: 60 },
        children: [new TextRun({ text: item, size: 22, font: "Arial" })],
      })),

      new PageBreak(),

      // ════════════════════════════════════════════════════════════
      // SECTION 9: IMPLEMENTATION CHECKLIST
      // ════════════════════════════════════════════════════════════
      heading("9. Implementation Checklist"),
      spacer(),

      ...[
        "Add whatsapp_business_account_id to config.py and .env",
        "Create scripts/register_templates.py with all Donna templates",
        "Run the registration script and wait 24\u201348h for approval",
        "Check template approval status via GET /message_templates",
        "Update donna/brain/sender.py with 24-hour window check and routing logic",
        "Add _is_window_open() helper that queries last user ChatMessage timestamp",
        "Map candidate categories to template names via CATEGORY_TEMPLATE_MAP",
        "Add _extract_template_params() to split LLM-generated messages into variable slots",
        "Test: send proactive message to user who messaged >24h ago (should use template)",
        "Test: send proactive message to user who messaged <24h ago (should use freeform)",
        "Monitor WhatsApp quality rating in Meta Business Manager after launch",
        "Track template delivery success rates vs freeform delivery rates",
      ].map((item, i) => new Paragraph({
        numbering: { reference: "numbers", level: 0 },
        spacing: { after: 80 },
        children: [new TextRun({ text: item, size: 22, font: "Arial" })],
      })),

      spacer(),
      divider(),

      // ── Sources ────────────────────────────────────────────────
      heading("Sources", HeadingLevel.HEADING_2),
      spacer(),
      ...["Meta Business Management API \u2014 Message Templates: developers.facebook.com/docs/whatsapp/business-management-api/message-templates",
          "WhatsApp Cloud API \u2014 Sending Templates: developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates",
          "WhatsApp Pricing: developers.facebook.com/docs/whatsapp/pricing",
          "WhatsApp Template Guidelines: developers.facebook.com/docs/whatsapp/message-templates/guidelines",
          "WhatsApp Messaging Limits: developers.facebook.com/docs/whatsapp/messaging-limits",
      ].map(text => new Paragraph({
        numbering: { reference: "bullets", level: 0 },
        spacing: { after: 60 },
        children: [new TextRun({ text, size: 20, font: "Arial", color: "555555" })],
      })),
    ],
  }],
});

// ── Write file ──────────────────────────────────────────────────
Packer.toBuffer(doc).then(buffer => {
  const outPath = "/sessions/funny-elegant-brahmagupta/mnt/app/whatsapp_templates_reference.docx";
  fs.writeFileSync(outPath, buffer);
  console.log(`Written to ${outPath}`);
});
