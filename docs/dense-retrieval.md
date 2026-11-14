# BGE-M3 검색 설정

기본 질문 검색은 추가 모델 설치가 필요 없는 TF-IDF입니다. BGE-M3는 선택 기능이며,
완료된 분석에 고정된 공식 자료 범위 안에서 관련 문장을 찾습니다. LLM이나 취약점 판정
자체를 바꾸지는 않습니다. 실험 스크립트의 Hybrid·재순위 결과는 현재 웹 서비스의 검색
모드가 아닙니다.

## Windows + NVIDIA GPU

호환되는 NVIDIA 드라이버와 충분한 디스크 공간이 필요합니다. CUDA 드라이버가 없는
컴퓨터는 아래 GPU 설치 대신 다음 절의 `dense` 옵션을 사용하세요. 최초 설치와 모델
다운로드는 여러 GB의 공간을 사용합니다. 다음 예시는 PowerShell에서 저장소 루트 기준이며,
가상환경·uv 캐시·Hugging Face 모델 캐시와 임시 파일을 D 드라이브에 둡니다.

```powershell
$env:UV_PROJECT_ENVIRONMENT = 'D:\cti-agent-runtime\project-env'
$env:UV_CACHE_DIR = 'D:\cti-agent-runtime\uv-cache'
$env:HF_HOME = 'D:\cti-agent-runtime\huggingface'
$env:TEMP = 'D:\cti-agent-runtime\tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
```

기존 `.env` 파일에 다음을 설정합니다. 경로는 사용 가능한 위치로 조정하세요.

```dotenv
RETRIEVAL_MODE=dense
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_CACHE_DIRECTORY=D:/cti-agent-runtime/embedding-cache
DENSE_MIN_SIMILARITY=0.45
```

```powershell
uv run --frozen --extra dense-cuda python scripts/dev.py --retrieval-deps dense-cuda
```

설치된 PyTorch의 CUDA 인식 여부는 동일한 환경에서 확인할 수 있습니다.

```powershell
uv run --frozen --extra dense-cuda python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CUDA unavailable')"
```

`False`이면 NVIDIA 드라이버·GPU 호환성 및 `dense-cuda` 설치를 확인하세요. 모델을
불러올 때 CUDA를 먼저 선택하고, 사용할 수 없는 경우 macOS의 MPS, 그 다음 CPU를
선택합니다. `dense-cuda`는 Windows AMD64 및 Linux x86-64의 CUDA용 설치입니다.

## macOS 또는 일반 설치

`.env`에 `RETRIEVAL_MODE=dense`를 설정한 뒤 다음 명령을 실행합니다. Apple Silicon의
MPS가 사용 가능하면 자동으로 선택하고, 그 외에는 사용 가능한 장치를 선택합니다.

```bash
uv run --frozen --extra dense python scripts/dev.py --retrieval-deps dense
```

`dense`와 `dense-cuda`는 서로 다른 PyTorch 배포판을 선택하므로 둘 중 하나만 지정합니다.
실행기 바깥의 `uv run --extra ...`와 실행기의 `--retrieval-deps ...`는 같은 값이어야 합니다.
일반 `uv sync` 또는 extra 없는 `uv run`은 선택 의존성을 제거할 수 있습니다. TF-IDF로
되돌리려면 `.env`의 `RETRIEVAL_MODE=tfidf`를 설정하고 기본 실행 명령을 사용하세요.

현재 Compose 이미지는 기본 TF-IDF 의존성으로 빌드됩니다. 위 선택 설치와 GPU 실행은
로컬 개발 실행기에서 사용합니다.

## 검색 점수와 모델 캐시

`DENSE_MIN_SIMILARITY`의 기본값 `0.45` 미만인 결과는 제외합니다. 질문에 명시된 CVE와
정확히 일치하는 자료는 점수 기준과 관계없이 우선합니다. 점수 기준은 소규모 질문 표본에서
정한 시작값이며, 관련 자료를 놓치거나 무관한 자료가 포함될 가능성이 있습니다. 값은 -1~1
범위에서 조정하고 실제 업무 질문으로 평가해야 합니다. 관련 자료가 없으면 학교 API를
호출하지 않고 근거 부족을 표시합니다.

최초 질문은 모델을 다운로드하고 메모리에 올리는 동안 오래 걸릴 수 있습니다. 현재는
질문 요청을 접수하는 API에서 근거 검색을 먼저 수행하므로, 준비가 끝나야 작업 대기
상태가 표시됩니다. 이후에도 처음 보는 문서는 임베딩을 만들어 캐시에 저장합니다.
캐시에는 검색에 사용된 텍스트에서 계산한 벡터가 포함되므로 운영 데이터와 같이 관리하세요.
캐시 파일이 손상되면 다시 계산하며, 완성되지 않은 파일이 정상 캐시를 덮어쓰지 않습니다.

## 평가 및 검증

일반 시험은 모델을 다운로드하지 않습니다. 실제 모델을 검증할 때만 예를 들어 다음처럼
환경 변수를 지정합니다. 모델이 캐시에 없으면 네트워크 다운로드가 발생할 수 있습니다.

```powershell
$env:CTI_RUN_REAL_BGE = '1'
# 이미 내려받은 모델을 쓰려면 선택적으로 지정: $env:CTI_TEST_BGE_MODEL = 'D:/path/to/bge-m3'
uv run --frozen --extra dense-cuda pytest tests/integration/test_dense_retrieval_real.py
```

`scripts/evaluate_*.py`는 CUDA, MPS, CPU 순서로 장치를 고르고 `EMBEDDING_MODEL` 환경
변수로 로컬 모델 경로를 지정할 수 있습니다. Ubuntu OSV 표본 생성 스크립트는 기본적으로
`data/raw/ubuntu/official_osv/osv-all.tar.xz`를 읽습니다. 다른 경로를 사용하려면
`UBUNTU_OSV_ARCHIVE` 환경 변수에 파일 경로를 지정하세요. 이 평가는 자료를 자동으로
받아오거나 서비스의 자료 수집을 대신하지 않습니다.
