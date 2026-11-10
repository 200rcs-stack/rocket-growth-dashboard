// Present legacy cached AI/manual copy consistently without changing file names,
// identifiers or ordinary words such as 실행, 진행 and 집행.
export function readableTerms(value:string):string {
  return String(value??'').replaceAll('SKU·등급 행','상품·옵션·등급별 항목').replace(/(\d+)\s*행/g,'$1개 항목');
}
