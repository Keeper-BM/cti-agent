import { Icon } from "./Icon";

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
    <section className="panel placeholder-panel">
      <div className="placeholder-heading">
        <span className="badge unavailable">준비 중</span>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      <div className="placeholder-content">
        <div className="placeholder-icon">
          <Icon name="findings" />
        </div>
        <div>
          <h3>미구현 기능</h3>
          <p>예정된 제공 범위</p>
          <div className="placeholder-fields">
            <span>제공 예정 정보</span>
            {columns.map((column) => (
              <span key={column}>{column}</span>
            ))}
          </div>
          <a className="inline-link" href="#/example">
            시험 예제 <Icon name="arrow" />
          </a>
        </div>
      </div>
    </section>
  );
}
