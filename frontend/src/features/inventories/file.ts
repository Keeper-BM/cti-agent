export const MAX_INVENTORY_BYTES = 2 * 1024 * 1024;

export async function readInventoryFile(file: File): Promise<string> {
  const csv = file.name.toLowerCase().endsWith(".csv");
  if (!csv && !file.name.toLowerCase().endsWith(".json")) {
    throw new Error("확장자가 .json 또는 .csv인 파일을 선택하세요.");
  }
  if (file.size > MAX_INVENTORY_BYTES) {
    throw new Error("파일 크기는 최대 2 MiB입니다.");
  }
  let content: string;
  try {
    content = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
  } catch {
    throw new Error("파일을 읽을 수 없습니다. UTF-8 형식의 JSON·CSV 파일을 선택하세요.");
  }
  if (csv) return content;
  try {
    const parsed: unknown = JSON.parse(content);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
  } catch {
    throw new Error("JSON 문법을 확인하세요. 입력 예제를 내려받아 파일 형식을 확인할 수 있습니다.");
  }
  // Send the original text: the API also rejects duplicate fields and non-finite numbers.
  return content;
}
