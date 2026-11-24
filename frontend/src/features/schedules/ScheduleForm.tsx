import { useCallback, useState } from "react";
import type { HttpClient } from "../../api/client";
import { Icon } from "../../shared/components/Icon";
import { Notice } from "../../shared/components/Notice";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { listAssets } from "../assets/api";
import { ReportPages } from "../reports/ReportPreview";
import { saveSchedule, scheduleLink, type Schedule, type ScheduleInput } from "./api";

export const weekdays = ["월", "화", "수", "목", "금", "토", "일"];
const selectionLimit = 20;
const assetPageSize = 20;

export function ScheduleForm({ api, schedule }: { api: HttpClient; schedule?: Schedule }) {
  const [name, setName] = useState(schedule?.name ?? "");
  const [frequency, setFrequency] = useState<ScheduleInput["frequency"]>(
    schedule?.frequency ?? "DAILY",
  );
  const [weekday, setWeekday] = useState(schedule?.weekday ?? 0);
  const [localTime, setLocalTime] = useState(schedule?.local_time ?? "09:00");
  const [selected, setSelected] = useState(schedule?.assets ?? []);
  const [page, setPage] = useState(0);
  const action = useAction();
  const loadAssets = useCallback(
    (signal: AbortSignal) => listAssets(api, page * assetPageSize, signal),
    [api, page],
  );
  const assets = usePollingQuery(loadAssets, null);
  const selectedIds = new Set(selected.map((asset) => asset.id));
  const back = schedule ? scheduleLink(schedule.id) : "#/schedules";

  async function submit() {
    if (!name.trim() || !localTime || !selected.length || action.pending) return;
    await action.run(async () => {
      const saved = await saveSchedule(
        api,
        {
          name: name.trim(),
          frequency,
          weekday: frequency === "WEEKLY" ? weekday : null,
          local_time: localTime,
          asset_ids: selected.map((asset) => asset.id),
        },
        schedule?.id,
      );
      window.location.hash = scheduleLink(saved.id);
    }, "예약을 저장했습니다.");
  }

  return (
    <div className="schedule-layout">
      <a className="run-back" href={back}>
        <Icon name="arrow" /> {schedule ? "예약 상세" : "예약 목록"}
      </a>
      <form
        className="work-card schedule-card schedule-form"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <h2>{schedule ? "예약 수정" : "새 분석 예약"}</h2>
        <Notice error={action.error} />
        <fieldset disabled={action.pending} className="schedule-fields">
          <label className="schedule-name">
            예약 이름
            <input
              name="name"
              required
              maxLength={80}
              placeholder="예: 운영 서버 주간 점검"
              value={name}
              onChange={(event) => setName(event.currentTarget.value)}
            />
          </label>
          <label>
            반복 주기
            <select
              value={frequency}
              onChange={(event) => setFrequency(event.currentTarget.value as typeof frequency)}
            >
              <option value="DAILY">매일</option>
              <option value="WEEKLY">매주</option>
            </select>
          </label>
          {frequency === "WEEKLY" && (
            <label>
              실행 요일
              <select
                value={weekday}
                onChange={(event) => setWeekday(Number(event.currentTarget.value))}
              >
                {weekdays.map((day, index) => (
                  <option value={index} key={day}>
                    {day}요일
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            실행 시각 (KST)
            <input
              type="time"
              name="local_time"
              required
              value={localTime}
              onChange={(event) => setLocalTime(event.currentTarget.value)}
            />
          </label>
        </fieldset>
        <fieldset disabled={action.pending} className="schedule-targets">
          <legend>분석 대상</legend>
          <p>SSH가 설정된 활성 자산을 최대 {selectionLimit}대까지 선택할 수 있습니다.</p>
          {(schedule?.inaccessible_asset_count ?? 0) > 0 && (
            <p>접근 권한이 없는 자산을 제외하고 다시 저장할 수 있습니다.</p>
          )}
          <p className="schedule-selection-count" aria-live="polite">
            {selected.length}대 선택
          </p>
          {selected.length > 0 && (
            <ul className="schedule-chips" aria-label="선택한 자산">
              {selected.map((asset) => (
                <li key={asset.id}>
                  <button
                    type="button"
                    aria-label={`${asset.asset_name} 선택 해제`}
                    onClick={() =>
                      setSelected((list) => list.filter((item) => item.id !== asset.id))
                    }
                  >
                    {asset.asset_name} <Icon name="close" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <Notice error={assets.error} />
          {assets.error && (
            <button type="button" className="text-tool" onClick={assets.refresh}>
              <Icon name="refresh" /> 자산 다시 불러오기
            </button>
          )}
          {assets.data?.items.length ? (
            <ul className="target-rows" aria-label="등록 자산">
              {assets.data.items.map(({ id, asset_name, is_active, ssh_configured }) => {
                const checked = selectedIds.has(id);
                const eligible = is_active && ssh_configured;
                return (
                  <li key={id} className={checked ? "chosen" : undefined}>
                    <label className="target-option">
                      <input
                        type="checkbox"
                        className="target-check"
                        checked={checked}
                        disabled={!checked && (!eligible || selected.length >= selectionLimit)}
                        onChange={(event) => {
                          const next = event.currentTarget.checked;
                          setSelected((list) =>
                            next
                              ? [...list, { id, asset_name }]
                              : list.filter((item) => item.id !== id),
                          );
                        }}
                      />
                      <span className="target-name">
                        <strong>{asset_name}</strong>
                      </span>
                    </label>
                    {!is_active ? (
                      <span className="batch-review">비활성</span>
                    ) : ssh_configured ? (
                      <span className="batch-state">SSH 설정됨</span>
                    ) : (
                      <a href={`#/assets?asset=${id}&setup=ssh`}>SSH 설정</a>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            !assets.error && (
              <p role="status">{assets.data ? "등록된 자산이 없습니다." : "자산을 불러오는 중…"}</p>
            )
          )}
          {(assets.data?.total ?? 0) > assetPageSize && (
            <ReportPages
              label="예약 대상 자산"
              page={page}
              size={assetPageSize}
              total={assets.data!.total}
              setPage={setPage}
            />
          )}
        </fieldset>
        <div className="schedule-form-footer">
          <a className="button-link secondary-link" href={back}>
            취소
          </a>
          <button
            className="button-link primary-link"
            disabled={!name.trim() || !selected.length || !localTime || action.pending}
          >
            <Icon name="check" /> {action.pending ? "저장 중…" : "예약 저장"}
          </button>
        </div>
      </form>
    </div>
  );
}
