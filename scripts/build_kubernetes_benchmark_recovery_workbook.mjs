#!/usr/bin/env node
/** Build the blind Kubernetes benchmark-recovery review workbook. */

import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const { SpreadsheetFile, Workbook } = require("@oai/artifact-tool");

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const packetPath = path.join(
  root,
  "data/kubernetes/benchmark_recovery_audit/review_packet.json",
);
const knowledgePath = path.join(root, "data/kubernetes/knowledge.json");
const outputPath = path.join(
  root,
  "outputs/kubernetes-benchmark-recovery/kubernetes_benchmark_recovery_audit.xlsx",
);
const previewDir = "/tmp/kubernetes-benchmark-recovery-previews";

const packet = JSON.parse(await fs.readFile(packetPath, "utf8"));
const knowledge = JSON.parse(await fs.readFile(knowledgePath, "utf8"));
if (packet.length !== 20) {
  throw new Error(`expected 20 review cases, found ${packet.length}`);
}

const workbook = Workbook.create();
const review = workbook.worksheets.add("Review");
const documents = workbook.worksheets.add("Document IDs");
review.showGridLines = false;
documents.showGridLines = false;
review.tabColor = "#326CE5";
documents.tabColor = "#5F6B7A";

review.getRange("A1:I1").format.fill = "#173B65";
review.getRange("A1:I1").format.font = {
  bold: true,
  color: "#FFFFFF",
  size: 18,
};
review.getRange("A1:I1").format.rowHeight = 30;
review.getRange("A1").values = [["Kubernetes Benchmark Recovery — Blind Source Audit"]];
review.mergeCells("A1:I1");
review.getRange("A2:I2").format.fill = "#DCE8F7";
review.getRange("A2:I2").format.font = { color: "#173B65", italic: true };
review.getRange("A2").values = [[
  "These 20 authentic Stack Overflow questions test the source-selection process. They are permanently excluded from evaluation splits.",
]];
review.mergeCells("A2:I2");

const instructions = [
  ["Goal", "Open each source page and independently decide whether the pinned official Kubernetes corpus directly answers the core question."],
  ["Blind rule", "Do not consult accepted answers, prior pilots, retriever output, model predictions, or suggested labels."],
  ["Supported", "Choose supported only when an official section directly answers the core question; copy its document_id from the Document IDs sheet."],
  ["Unsupported", "Choose unsupported when the question is genuine but no pinned official Kubernetes section directly answers it; leave document ID blank."],
  ["Ambiguous / outdated", "Use ambiguous when context is insufficient; use outdated when the question depends on an obsolete Kubernetes version or architecture."],
  ["Finish", "Set review_status to approved only after checking the source and evidence. Save the workbook, then tell Codex: recovery audit reviewed and saved."],
];
review.getRange("A3:B8").values = instructions;
for (let row = 3; row <= 8; row += 1) {
  review.mergeCells(`B${row}:I${row}`);
}
review.getRange("A3:A8").format = {
  fill: "#E8EEF5",
  font: { bold: true, color: "#173B65" },
  verticalAlignment: "top",
};
review.getRange("B3:I8").format = {
  fill: "#F7F9FC",
  wrapText: true,
  verticalAlignment: "top",
};
review.getRange("A3:I8").format.borders = {
  preset: "all",
  style: "thin",
  color: "#CBD5E1",
};

const reviewHeaders = [
  "#",
  "case_id",
  "question",
  "source_url",
  "content_license",
  "reviewer_decision",
  "expected_document_id",
  "review_status",
  "reviewer_notes",
];
const reviewRows = packet.map((row) => [
  row.review_order,
  row.case_id,
  row.question,
  row.source_url,
  row.content_license,
  row.reviewer_decision,
  row.expected_document_id,
  row.review_status,
  row.reviewer_notes,
]);
review.getRange("A11:I11").values = [reviewHeaders];
review.getRange(`A12:I${11 + reviewRows.length}`).values = reviewRows;
review.getRange("A11:I11").format = {
  fill: "#326CE5",
  font: { bold: true, color: "#FFFFFF" },
  wrapText: true,
  verticalAlignment: "center",
};
review.getRange("A11:I31").format.borders = {
  preset: "all",
  style: "thin",
  color: "#D8DEE8",
};
review.getRange("A12:E31").format.fill = "#F5F7FA";
review.getRange("F12:I31").format.fill = "#FFF4CC";
review.getRange("A12:I31").format.verticalAlignment = "top";
review.getRange("B12:I31").format.wrapText = true;
review.getRange("A12:A31").setNumberFormat("0");
review.getRange("F12:F31").dataValidation = {
  rule: {
    type: "list",
    values: ["supported", "unsupported", "ambiguous", "outdated"],
  },
};
review.getRange("H12:H31").dataValidation = {
  rule: { type: "list", values: ["pending", "approved"] },
};
review.tables.add("A11:I31", true, "KubernetesRecoveryAudit");
review.freezePanes.freezeRows(11);
review.freezePanes.freezeColumns(2);

const reviewWidths = [18, 32, 62, 55, 16, 20, 30, 15, 42];
for (let index = 0; index < reviewWidths.length; index += 1) {
  review.getRangeByIndexes(0, index, 31, 1).format.columnWidth = reviewWidths[index];
}
review.getRange("1:2").format.rowHeight = 28;
review.getRange("3:8").format.rowHeight = 34;
review.getRange("11:11").format.rowHeight = 32;
review.getRange("12:31").format.rowHeight = 52;

documents.getRange("A1:D1").format.fill = "#173B65";
documents.getRange("A1:D1").format.font = {
  bold: true,
  color: "#FFFFFF",
  size: 18,
};
documents.getRange("A1").values = [["Pinned Official Kubernetes Document IDs"]];
documents.mergeCells("A1:D1");
documents.getRange("A2:D2").format.fill = "#DCE8F7";
documents.getRange("A2:D2").format.font = { color: "#173B65", italic: true };
documents.getRange("A2").values = [[
  "Use Excel search/filter to find a relevant official section. Copy document_id into the Review sheet only when the section directly supports the answer.",
]];
documents.mergeCells("A2:D2");
const documentHeaders = ["document_id", "title", "product_area", "official_source_url"];
const documentRows = knowledge.map((row) => [
  row.document_id,
  row.title,
  row.product_area,
  row.source,
]);
documents.getRange("A4:D4").values = [documentHeaders];
documents.getRangeByIndexes(4, 0, documentRows.length, 4).values = documentRows;
documents.getRange("A4:D4").format = {
  fill: "#5F6B7A",
  font: { bold: true, color: "#FFFFFF" },
  wrapText: true,
};
documents.getRangeByIndexes(4, 0, documentRows.length, 4).format = {
  borders: { preset: "all", style: "thin", color: "#E1E6ED" },
  verticalAlignment: "top",
};
documents.getRangeByIndexes(4, 1, documentRows.length, 3).format.wrapText = true;
documents.tables.add(`A4:D${4 + documentRows.length}`, true, "KubernetesDocuments");
documents.freezePanes.freezeRows(4);
documents.getRange("A:A").format.columnWidth = 30;
documents.getRange("B:B").format.columnWidth = 55;
documents.getRange("C:C").format.columnWidth = 18;
documents.getRange("D:D").format.columnWidth = 70;
documents.getRange("1:2").format.rowHeight = 28;
documents.getRange("4:4").format.rowHeight = 30;

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

await fs.mkdir(previewDir, { recursive: true });
for (const [sheetName, fileName] of [
  ["Review", "review.png"],
  ["Document IDs", "document_ids.png"],
]) {
  const preview = await workbook.render({
    sheetName,
    range: sheetName === "Review" ? "A1:I18" : "A1:D12",
    scale: 1,
    format: "png",
  });
  await fs.writeFile(
    path.join(previewDir, fileName),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

const overview = await workbook.inspect({
  kind: "sheet,table",
  maxChars: 6000,
  tableMaxRows: 4,
  tableMaxCols: 9,
});
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  maxChars: 3000,
});
console.log(JSON.stringify({ outputPath, previewDir }));
console.log(overview.ndjson);
console.log(formulaErrors.ndjson);
await fs.rm(`${outputPath}.inspect.ndjson`, { force: true });
