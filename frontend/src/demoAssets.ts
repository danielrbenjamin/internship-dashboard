// ZIP with the fictional main.tex used by the demo.
const archive = "UEsDBBQAAAAAAAAAIQB5AqzCZQAAAGUAAAAIAAAAbWFpbi50ZXhcZG9jdW1lbnRjbGFzc3thcnRpY2xlfQpcYmVnaW57ZG9jdW1lbnR9CkFsZXggTW9yZ2FuIC0tLSBzYW1wbGUgYXBwbGljYXRpb24gbWF0ZXJpYWxzClxlbmR7ZG9jdW1lbnR9ClBLAQIUABQAAAAAAAAAIQB5AqzCZQAAAGUAAAAIAAAAAAAAAAAAAACAAQAAAABtYWluLnRleFBLBQYAAAAAAQABADYAAACLAAAAAAA=";

export function demoPdf(path: string) {
  const heading = path.includes("cover") ? "Sample cover letter" : "Alex Morgan";
  const stream = "BT /F1 20 Tf 72 720 Td (" + heading +
    ") Tj /F1 11 Tf 0 -32 Td (Demo workspace - mechanical engineering application) Tj ET\n";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    "<< /Length " + stream.length + " >>\nstream\n" + stream + "endstream",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = objects.map((object, index) => {
    const offset = pdf.length;
    pdf += String(index + 1) + " 0 obj\n" + object + "\nendobj\n";
    return String(offset).padStart(10, "0") + " 00000 n \n";
  });
  const xref = pdf.length;
  pdf += "xref\n0 6\n0000000000 65535 f \n" + offsets.join("") +
    "trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + xref + "\n%%EOF\n";
  return new Blob([pdf], {type: "application/pdf"});
}

const urls = new Map<string, string>();
export function demoAsset(path: string) {
  const kind = path.endsWith("/zip") ? "source" : path.endsWith("/txt") ? "text" :
    path.includes("cover") ? "cover" : "resume";
  const cached = urls.get(kind);
  if (cached) return cached;
  const file = kind === "source"
    ? new Blob([Uint8Array.from(atob(archive), char => char.charCodeAt(0))], {type: "application/zip"})
    : kind === "text"
      ? new Blob(["Dear hiring team,\n\nI would be excited to bring my prototype testing experience to your team.\n\nAlex Morgan"],
        {type: "text/plain"})
      : demoPdf(path);
  const url = URL.createObjectURL(file);
  urls.set(kind, url);
  return url;
}
