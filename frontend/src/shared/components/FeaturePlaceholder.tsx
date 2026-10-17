export function FeaturePlaceholder({
  title,
  description,
  columns,
}: {
  title: string;
  description: string;
  columns: string[];
}) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <span className="badge">연동 전</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody />
        </table>
      </div>
      <div className="empty">
        <strong>이 기능은 아직 사용할 수 없습니다</strong>
        <p>실제 데이터 처리가 연결되면 결과와 공식 근거를 여기에서 확인할 수 있습니다.</p>
      </div>
    </section>
  );
}
