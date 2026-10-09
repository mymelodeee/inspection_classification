# 반도체 Inspection Map 자동 분석 지식 파일

작성일: 2026년 10월 9일  
범위: 웨이퍼 격자·불량 dot 이미지의 구조화, 공간 패턴 분류, bin별 방향·밀도 분석, Python 구현 및 사내 배포 설계

## 1. 핵심 판단과 확인 범위

제안하는 프로그램은 구현 가능한 문제다. 다만 이미지를 tensor로 변환하는 것은 입력 형식을 바꾸는 단계이며, 그 자체가 환형·선형·몰림성을 판단하지는 않는다. 패턴을 구분할 특징과 규칙 또는 학습된 모델이 추가로 필요하다.

권장 구성은 다음 세 기능의 결합이다.

1. 이미지 또는 원본 좌표를 정규화해 불량 위치·bin 정보를 구조화한다.
2. 공간 특징과 분류 모델을 이용해 환형·선형·몰림성 등 패턴을 판정한다.
3. 좌표에서 시계방향 구간·반경·bin별 건수와 밀도를 계산하고 결과를 설명한다.

이 문서의 문헌 설명은 출처에서 확인한 내용이며, 입력 채널·분석식·개발 순서·배포 구성은 해당 문헌과 요청 조건을 바탕으로 한 설계 제안이다. 실제 이미지·정답 라벨·원본 좌표를 받지 않았으므로 적용 정확도와 처리시간은 측정하지 않았다. 요청의 ‘0) 붙여준 텍스트’에 해당하는 별도 불량 유형 설명은 현재 메시지에 없으므로 반영하지 않았다.

## 2. Inspection dot map과 Wafer Bin Map의 차이

| 구분 | Inspection defect map | 전기적 검사 Wafer Bin Map |
|---|---|---|
| 기본 관측 단위 | 검출된 개별 defect 이벤트 | 칩 또는 die의 검사 결과 |
| 위치 | 연속 X·Y 좌표, 경우에 따라 die 내부 좌표 | die 행·열 |
| 한 칩의 정보 | 여러 defect와 여러 classification bin이 존재할 수 있음 | 검사 체계에 따른 die 결과 또는 bin |
| 빨간 점·불량 셀의 의미 | 검출 이벤트 표시일 수 있음 | 불량 die 표시 |
| 주요 집계 | defect 수, 검사면적당 밀도, 영향받은 die 수 | 불량 die 수, 검사 die 대비 비율 |

공개 WM 계열 연구는 전기적 검사 결과인 경우가 많다. WM811K 관련 원논문 [R1], MixedWM38 원저자 저장소 [R5], 국내 신규 패턴 연구 [R8]가 이러한 구분을 이해하는 데 유용하다. Inspection map의 defect 한 개를 불량 die 한 개로 자동 간주해서는 안 된다.

특히 `classification_bin`은 개별 defect의 범주이고, `spatial_pattern`은 웨이퍼에서 보이는 공간적 분포 유형이다. Bin 5가 항상 선형이라는 식으로 두 분류를 동일시하지 않는다. 같은 bin이 환형과 몰림성에 함께 나타날 수 있다.

## 3. 입력 데이터와 보존할 정보

### 3.1 입력 우선순위

1. 개별 defect의 원본 X·Y·classification bin을 포함한 CSV 또는 설비 export.
2. 원본 좌표와 함께 제공되는 map 이미지.
3. map 이미지와 bin별 총수 표.
4. map 이미지만 있는 경우.

3번에서는 bin별 전체 개수를 알 수 있어도 각 점의 bin 소속은 모를 수 있다. 모든 dot이 동일한 빨간색이면 전체 집계표만으로 ‘3시 방향의 Bin 5 개수’를 복원할 수 없다. 개별 점과 bin을 연결하는 데이터 또는 bin별 별도 map이 필요하다.

### 3.2 권장 테이블

| 테이블 | 주요 필드 | 용도 |
|---|---|---|
| wafer_metadata | wafer_key, lot_key, product, inspection_step, tool, recipe, timestamp | 집계·검증 그룹·추적 |
| wafer_geometry | center, radius, coordinate_unit, axis_direction, notch_orientation, rotation, mirror_flag | 좌표계 정합 |
| defects | wafer_key, defect_id, x, y, classification_bin, optional_size | 개별 불량 분석 |
| inspection_coverage | 검사 영역 mask 또는 polygon, 제외 영역, 검사 die | 밀도의 분모 |
| bin_summary | wafer_key, classification_bin, reported_count, count_scope | export와 추출 결과 대조 |
| annotations | patterns, optional_region, reviewer_status, label_version | 학습·검증 정답 |

동일 wafer라도 step·시간·재검사 여부가 다르면 별도 검사 인스턴스 키를 둔다. 합산할 때만 원본 defect 식별자와 재검사 규칙에 따라 중복을 처리한다. 서로 가까운 두 점을 임의로 하나의 defect로 합치지 않는다.

count_scope에는 전체 검사 결과인지, 화면 필터 적용 후 값인지, sampling 결과인지 기록한다. 이미지와 표의 범위가 다르면 개수 불일치를 추출 오류로 오판할 수 있다.

## 4. 1차 분류 체계

아래 분류는 WM 문헌의 기본 패턴 [R1, R3, R5]을 참고해 inspection 분석용으로 구성한 초안이다. 물리적 원인 분류가 아닌 공간 형태 분류다.

| 표시명 | 권장 내부 label | 구분 기준의 설계 방향 | 추가로 보고할 값 |
|---|---|---|---|
| 중심 몰림 | center | 중심부에 높은 면적 보정 밀도 | 중심 반경·건수·밀도 |
| 환형 | ring | 특정 반경대에 분포하며 각도 범위가 넓음 | 대표 반경·두께·각도 점유율 |
| 가장자리 환형 | edge_ring | 외곽 반경대의 넓은 각도 분포 | edge 거리·각도 점유율 |
| 가장자리 국부 몰림 | edge_local | 외곽의 제한된 각도 구간에 집중 | 시계방향 구간·반경 |
| 국부 몰림 | local_cluster | 한두 영역 또는 여러 영역에 군집 | 군집별 중심·면적·건수 |
| 선형 | linear | 직선에 가까운 길고 좁은 분포 | 선 방향·길이·폭·적합 잔차 |
| 호형·곡선형 | arc | 굽은 선 또는 부분적인 원호 | 원호 중심·반경·각도 범위 |
| 산재형 | scattered | 뚜렷한 형상 없이 퍼진 분포 | 검사면적당 밀도·공간 검정 |
| 광범위 고밀도 | widespread_dense | 검사 영역 전반에 높은 밀도 | coverage·전체 밀도 |
| 뚜렷한 패턴 없음 | no_clear_pattern | 정의한 패턴의 근거가 부족 | 검출 수·검사 범위 |

운영 상태로 `mixed`, `unknown`, `insufficient_data`, `extraction_failed`를 별도 기록한다. `mixed`는 가능하면 `[ring, linear]`처럼 구성 패턴을 함께 보존한다. `unknown`은 기존 패턴과 다른 경우, `insufficient_data`는 점이 너무 적거나 관측 범위가 불충분한 경우다.

‘산재형’은 시각적 표현이다. 공간적 무작위성은 검사 영역·관측 건수·검출 확률을 고려한 통계 검정으로 별도 평가한다. ‘패턴 없음’도 ‘무결함’이나 ‘수율 정상’을 의미하지 않는다. `linear`를 실제 scratch 결함으로 확정하려면 defect review 등 추가 증거가 필요하다.

## 5. 이미지에서 분석 입력을 만드는 방법

### 5.1 이미지 추출 경로

1. 웨이퍼 map 영역을 찾고 제목·범례·수치·UI를 제외한다.
2. 웨이퍼 중심·반경·테두리를 추정하고 원본 위에 overlay하여 확인한다.
3. notch·flat 또는 메타데이터를 이용해 회전·좌우반전·상하반전을 정합한다.
4. HSV 등 색공간에서 빨간 dot 후보를 추출한다. OpenCV의 `inRange`가 기본 수단이다 [T3].
5. 색상으로 분리한 mask에서 연결요소와 중심점을 얻는다 [T4].
6. 추출 좌표를 원본 위에 표시하고 원본 export 또는 집계표와 대조한다.

OpenCV의 일반적인 8bit HSV 표현에서 빨간색은 hue 범위 양 끝에 걸칠 수 있어 두 범위를 합치는 방식이 필요할 수 있다. 실제 임계값은 화면 팔레트와 저장 포맷으로 결정한다. 범용 임계값 하나를 모든 설비 화면에 적용한다고 가정하지 않는다.

회색 격자는 색 분리로 배제하는 것이 우선이다. 수평·수직선을 일괄 삭제하면 실제 선형 불량도 함께 지워질 수 있다. morphology opening 역시 작은 실제 dot을 지울 수 있으므로 원본 보존과 추출 검증이 필요하다.

### 5.2 이미지 기반 개수의 한계

서로 겹친 dot은 하나의 연결요소로 나타나고, 격자나 압축 노이즈 때문에 하나의 dot이 분리될 수도 있다. 큰 연결요소를 총 픽셀 면적÷평균 dot 면적으로 나누어 실제 개수라고 단정하면 안 된다. 확대 배율·marker 크기·겹침 정도에 따라 결과가 달라진다.

따라서 이미지 기반 결과는 `estimated_visible_dot_count`, 원본 레코드 집계는 `raw_defect_count`로 구분한다. DBSCAN이 잡음으로 판정한 점도 전체 defect 집계에서는 보존한다. 패턴 강조용 mask와 원본 집계용 데이터는 별도 관리한다.

### 5.3 Tensor 설계

RGB 이미지의 H×W×3 배열을 PyTorch에서 C×H×W tensor로 바꿀 수 있다. `ToImage()`는 값의 scale을 바꾸지 않으며, 영상값의 dtype·범위 변환은 `ToDtype()` 등으로 명시한다 [T1, T2]. 단순 RGB 입력보다 아래 구조를 초기 후보로 권장한다.

| 표현 | 형상 예시 | 보존하는 의미 |
|---|---|---|
| 전체 defect count map | 1×H×W | 각 공간 셀의 defect 수 |
| 검사 coverage mask | 1×H×W | 검사된 영역과 관측되지 않은 영역 구분 |
| bin별 count map | K×H×W | 분류 bin별 공간 분포 |
| 좌표 테이블 | N×필드 수 | 정확한 건수·방향·원본 추적 |

첫 모델은 전체 defect map과 coverage mask의 2채널부터 비교할 수 있다. Bin 소속이 확보되면 중요한 K개 bin과 기타 bin 채널을 추가한다. Bin 번호는 명목형 범주이므로 3, 10, 50을 밝기로 그대로 넣어 숫자 간 거리의 의미를 부여하지 않는다.

좌표가 있으면 원본 이미지를 축소하는 대신 `histogram2d`와 같은 집계로 count map을 만든다. 입력 해상도는 최소 구분할 선 폭·군집 크기를 기준으로 선택한다. 예를 들어 256×256은 실험 시작값이지 표준값이 아니다. Count map은 셀의 개수가 합산되어 전체 건수가 유지되어야 한다. 범주 mask는 범주가 섞이는 보간을 피한다. Resize 이전·이후 건수를 무조건 같다고 가정하지 않는다.

모델 입력에 `log1p(count)`를 적용해 고밀도 영역의 지배를 줄일 수 있지만, 총수·원본 count map은 별도로 보존한다. 이미지별 최대값으로 나누기만 하면 10개와 1,000개 wafer의 강도 차이가 사라질 수 있다. Mask의 0/1 값이나 명목형 bin 번호에 영상용 255 나누기를 적용하지 않는다.

## 6. 시계방향 및 반경 분석

### 6.1 방향의 기준

최초 출력은 ‘화면 위쪽을 12시’로 정의할 수 있다. 설비 또는 wafer 간 물리적 방향을 비교하려면 notch 기준 회전·반전 정합이 선행되어야 한다. 방향 기준을 모르는 이미지는 `display_relative`로 표시하고 물리적 wafer 방향이라고 표현하지 않는다.

화면 좌표에서 x는 오른쪽, y는 아래쪽으로 증가하고 중심이 (cx, cy), 반경이 R일 때 다음과 같이 정의한다.

```text
dx = x - cx
dy = cy - y
r_normalized = sqrt(dx**2 + dy**2) / R
theta_deg = degrees(atan2(dx, dy)) % 360
```

theta=0°는 12시, 90°는 3시, 180°는 6시, 270°는 9시다. 이 식은 화면 좌표 기준이며, 실제 설비 좌표는 축 방향을 먼저 변환한다. 중심점은 각도가 정의되지 않으며, 중심에 매우 가까운 점은 작은 좌표 오차에도 방향이 크게 바뀌므로 별도 중심 영역으로 집계한다. 중심 영역 크기는 검증 데이터로 정한다.

12개 시각의 중심을 기준으로 각 30° 구간을 만들 경우 다음 식을 쓴다.

```text
sector_index = floor(((theta_deg + 15) % 360) / 30)
clock_hour = 12 if sector_index == 0 else sector_index
```

12시 sector는 345° 이상 또는 15° 미만이다. ‘2시부터 4시’처럼 폭을 가진 구간은 시작·끝 각도를 함께 저장하여 해석 차이를 없앤다. 11시와 1시의 평균이 6시가 되는 일반 산술평균은 사용하지 않는다. 원형 평균이나 원형 이동창을 쓰며, 서로 반대편 군집이 있으면 하나의 평균 방향으로 합치지 않는다.

### 6.2 무엇을 셀 것인가

| 지표 | 정의 | 주의점 |
|---|---|---|
| N(b,s) | bin b의 sector s에 속한 defect 수 | 개별 defect와 bin 연결 필요 |
| bin 내부 점유율 | N(b,s) / bin b의 전체 defect 수 | 해당 bin의 공간적 집중 |
| 영역 내 bin 구성비 | N(b,s) / sector s의 전체 defect 수 | 영역에서 어떤 bin이 우세한지 |
| defect density | N(b,s) / sector s의 유효 검사면적 | 검사 범위 차이를 보정 |
| affected die 수 | defect가 하나 이상 있는 고유 die 수 | defect 수와 별개 |
| affected die 비율 | affected die 수 / 검사 die 수 | 전기적 fail 비율과 동일하지 않음 |

분모가 0이면 0%로 표시하지 않고 계산 불가로 기록한다. 면적을 알 수 없으면 ‘관측 점의 분포’만 보고하고 면적 보정 밀도는 출력하지 않는다.

반경 histogram에서 원환 면적은 반경이 커질수록 커진다. 동일 폭 반경 구간의 건수만 비교하면 균일한 분포도 외곽이 더 많아 보인다. 반경 [r1,r2]의 전체 원환 면적은 π(r2²−r1²)이고, 실제 분석에는 이 영역과 검사 mask의 교집합 면적을 쓴다.

### 6.3 ‘몰림’ 판정

최대 sector는 임의 분포에서도 항상 존재한다. 최대 sector라는 이유만으로 이상이라고 판정하지 않는다. 초기에는 구간별 건수와 밀도를 서술하고, 알람은 정상 참고군의 제품·step·recipe·coverage 조건을 맞춰 보정한다.

후보 지표는 `영역 밀도 / 참고 밀도`와 정상 참고군 대비 변화다. 검사 영역 내에서 관측 건수를 고정한 Monte Carlo 분포를 비교 기준으로 사용할 수도 있다. 이때 검사·검출 확률이 균일한지 확인하고, 불균일하면 해당 확률 또는 정상 참고 분포를 반영한다. 여러 sector와 여러 bin을 동시에 탐색하면 다중 비교에 따른 오경보도 검증해야 한다.

보고 예시용 템플릿:

> {pattern} 패턴이 관찰됨. {orientation_basis} 기준 {start_clock}~{end_clock} 방향, 정규화 반경 {r_low}~{r_high}에 Bin {bin_id}가 {count}개 분포함. 해당 bin 전체의 {share}%이며, 유효 검사면적 보정 밀도는 참고군의 {ratio}배임. {quality_status}.

없는 bin·면적·참고군 정보를 추정하여 문장을 채우지 않는다.

## 7. 모델 선택과 특징 설계

### 7.1 1단계: 좌표 및 설명 가능한 기준 모델

| 목표 | 후보 방법 | 판정에 사용할 특징 |
|---|---|---|
| 몰림성 | DBSCAN, 밀도 추정 | 군집 수·최대 군집 점유율·군집 면적 |
| 선형 | PCA, RANSAC 직선 적합, Hough/Radon | 고유값 비율·길이/폭·잔차·선 지지율 |
| 환형 | 반경 밀도·원 또는 원환 적합 | 피크 반경·반경 폭·각도 coverage |
| 국부 외곽 몰림 | 반경×각도 격자 | 외곽 밀도·sector 집중도 |
| 혼합 패턴 | 군집별 특징, 다중 적합 | 패턴별 영역·점 소속·중복 여부 |

DBSCAN은 군집을 찾는 알고리즘이지 군집에 ‘ring’이나 ‘scratch’라는 이름을 자동으로 붙이는 분류기는 아니다 [T6]. DBSCAN의 eps는 화면 pixel보다 정규화된 wafer 좌표 또는 물리 단위에서 관리한다. 밀도가 다른 군집·드문 선형 점·끊긴 환형에서는 eps와 min_samples에 민감할 수 있다.

PCA의 큰 고유값 비율만으로 선형을 확정하지 않는다. 멀리 떨어진 두 blob도 길쭉한 분포가 될 수 있으므로 연속성·직선 잔차·폭을 함께 본다. Hough는 격자 제거 후 defect 후보에 적용한다 [T5].

환형 판정도 반경 피크만으로 충분하지 않다. 한쪽 외곽의 blob은 반경이 비슷할 수 있으므로 각도 coverage를 함께 확인한다. Wafer 중심 기준 환형과 중심이 어긋난 원형 패턴을 구분해야 하면 fitted circle의 중심 offset을 추가한다.

특징을 RandomForest·ExtraTrees·gradient boosting 등 분류기에 넣어 기준 모델을 만든다. 문헌 [R2, R3]의 특징 기반 접근과 CNN의 상호 보완성이 참고 근거다. 개별 알고리즘의 우열은 실제 독립 검증셋으로 결정한다.

### 7.2 2단계: CNN 및 결합 모델

정답이 있는 내부 map이 확보되면 소형 CNN 또는 ResNet 계열을 비교한다. Shape tensor와 총 defect 수·bin 비율·반경 통계 등 수치 특징을 결합하는 방법도 후보가 된다.

혼합 패턴은 여러 label이 동시에 참일 수 있으므로 sigmoid 기반 다중 label 분류가 자연스럽다. 모든 map을 단일 softmax class에 강제 배정하는 경우 환형+선형의 구성 정보가 사라질 수 있다. 학습 정답 체계부터 다중 label 여부를 정해야 한다.

최종 출력은 유형별 score와 공간 통계이며, score를 별도 calibration 없이 실제 확률이라고 단정하지 않는다. 미지 패턴 검출은 단순 최대 softmax 임계값만으로 보장되지 않는다. 국내 연구 [R8]처럼 기존 class 영역에서 벗어나는 정도를 활용하는 방법도 검토할 수 있다.

### 7.3 3단계: 혼합 패턴별 영역 분리

‘환형과 선형이 함께 있다’에서 더 나아가 ‘Bin 5 중 환형에 속한 점과 선형에 속한 점을 각각 센다’면 패턴별 영역 분리가 필요하다. WaferSegClassNet [R6]과 SePArate [R7]가 관련 출발점이다. 특히 SePArate는 image 수준 label을 이용한 혼합 패턴의 pixel 수준 분리를 다룬다.

Segmentation mask의 pixel 수를 원본 defect 수로 간주하지 않는다. 예측 영역에 원본 좌표를 연결하여 다시 집계한다. 겹치는 패턴에 하나의 defect를 중복 배정할지, 주 패턴 하나에 배정할지 명시해야 전체 수와 합산 수가 모순되지 않는다. Grad-CAM은 모델의 반응 위치를 보여주는 설명 자료이며, 정밀한 개수 집계용 정답 영역으로 간주하지 않는다.

### 7.4 ViT의 위치

요청에 포함된 2024년 ViT 논문 [R9]의 핵심은 ViT 기반 데이터 증강으로 class 불균형을 줄이고 CNN 분류 성능을 개선하는 것이다. ‘tensor로 바꾸어 ViT에 넣으면 위치별 개수까지 자동 해결된다’는 연구가 아니다. 초기 개발에서는 추출 품질과 기준 모델을 먼저 확인하고, 소수 class가 명확한 병목일 때 증강을 비교하는 편이 합리적이다.

## 8. 검증과 실패 방지

| 평가 단위 | 필수 확인 |
|---|---|
| 이미지 추출 | 원본 좌표 대비 검출 precision·recall, 위치 오차, 개수 오차 |
| 방향 정합 | 12·3·6·9시, notch 회전, 좌우반전, 각도 경계의 결과 |
| 패턴 분류 | 유형별 precision·recall·F1, macro F1, confusion matrix |
| 다중 label | label별 F1, micro/macro F1, 혼합 패턴 누락 |
| 위치·영역 | sector 건수 오차, 군집 위치 오차, 필요한 경우 IoU·Dice |
| 미지·품질 불량 | unknown 검출률, 오경보, 판정 보류율 |
| 운영 | 처리시간 p50/p95, 실패율, 제품·step·설비별 편차 |

동일 wafer의 반복 촬영·다른 bin view·증강본이 train과 test에 섞이지 않도록 먼저 원본 검사 인스턴스를 묶는다. 동일 lot과 유사 공정 조건의 상관성을 고려해 lot 단위 분리를 적용하고, 이후 시점의 데이터를 별도 blind test로 둔다. 추가로 처음 보는 제품·설비·이미지 template에 대한 평가가 필요하다.

증강은 분할 이후 train에서만 수행한다. 회전 증강으로 형상 label은 유지할 수 있지만 시계방향 정답은 함께 회전해야 한다. 추론 시 방향 분석은 원래 물리 좌표로 수행한다. 불균형 데이터에서 전체 accuracy 한 개로 모델을 선택하지 않는다.

고정 시험 자료에는 빈 map, 단일 점, 겹친 점, 양쪽 군집, 끊긴 ring, 희박한 선형, 격자와 겹친 dot, 부분 검사, 저해상도, 빨간 범례, bin 누락, 방향 미상 이미지를 포함한다. 합성 자료는 계산 검증에 활용하고, 실제 적용 성능은 독립된 실제 자료로 평가한다.

Pattern은 원인 추적의 단서다. 환형만으로 특정 공정이나 설비가 원인이라고 확정하지 않는다. 공정 경로·chamber 이력·시간적 발생·동일 조건의 비교군과 결합하는 별도 분석이 필요하다.

## 9. 개발 및 사내 배포 구성

### 9.1 개발 단계와 완료 조건

| 단계 | 산출물 | 완료 조건 |
|---|---|---|
| 1. 입력 정리 | 데이터 계약·라벨 가이드·좌표 변환 규칙 | dot·bin·die의 의미와 방향 기준 확정 |
| 2. 추출 및 위치 분석 | 이미지 overlay·좌표 테이블·sector×bin 집계 | 원본과의 추출·집계 오차 확인 |
| 3. 패턴 기준 모델 | 특징 기반 분류·유형별 근거 | 내부 blind 데이터의 유형별 성능 확인 |
| 4. CNN 비교 | 동일 split에서 모델 비교 | 기준 모델 대비 유의한 운영상 개선 확인 |
| 5. 프로그램 연결 | 업로드 UI·batch 실행·결과 JSON | 동일 입력의 재현 가능한 분석 |
| 6. 배포 | container·검증 결과·버전 관리·rollback | 운영 환경에서 정상·실패 경로 검증 |

초기 라벨링 물량은 고정 정답이 없다. 각 유형의 전형·경계·혼합 사례를 모아 추출 시험을 시작하고, lot 다양성과 class별 learning curve를 보면서 확대한다. 소수 예제로 만든 시연과 양산 검증 완료를 구분한다.

### 9.2 Python 모듈 초안

```text
ingest.py         원본 CSV 또는 이미지 입력
geometry.py       ROI, 중심, 반경, 방향 정합
extract.py        dot mask, 연결요소, 좌표 추출
coverage.py       검사 영역과 면적 계산
spatial.py        반경, sector, 밀도, 군집 통계
features.py       선형·환형·몰림성 특징
predict.py        규칙 또는 학습 모델 추론
report.py         결과 JSON, overlay, 근거 문장
app.py            사용자 화면
```

분석 코어는 UI와 분리된 Python 함수·패키지로 구성한다. 파일 업로드 방식은 Streamlit 같은 UI로 시작할 수 있고, 사내 시스템이 HTTP를 요구하면 API를 추가한다. 배치가 요구되면 같은 분석 함수를 CLI에서 호출한다. CI/CD는 분석 알고리즘이 아니라 이 코드·모델을 검증하고 배포하는 절차다.

모델 가중치, bin mapping, 전처리 설정, 좌표 규칙, label version을 한 버전 묶음으로 배포한다. 변경 시 고정 회귀 자료의 방향·건수·유형 결과를 확인하고 기존 버전으로 복귀 가능하게 한다. 실제 내부 배포 명령과 인증·포트·리소스 조건은 해당 운영 플랫폼 문서로 별도 확정한다.

LLM은 필수 구성요소가 아니다. 필요하면 분석기가 생성한 JSON을 문장으로 요약하도록 추가할 수 있다. 유형 근거·개수·시계방향은 분석기의 검증된 값을 사용한다.

### 9.3 결과 계약 예시

```json
{
  "schema_version": "1.0",
  "input_mode": "raw_coordinates",
  "orientation_basis": "notch_registered",
  "analysis_status": "ok",
  "patterns": ["ring", "local_cluster"],
  "pattern_scores": {},
  "raw_defect_count": null,
  "estimated_visible_dot_count": null,
  "affected_die_count": null,
  "bin_sector_statistics": [],
  "clusters": [],
  "quality_flags": [],
  "model_version": "to_be_assigned",
  "preprocess_version": "to_be_assigned"
}
```

위 JSON은 데이터 계약 예시이며 분석 결과가 아니다. 미확인 값을 0으로 채우지 않고 null 또는 명시적 상태로 남긴다.

## 10. 우선 읽을 논문과 자료

### R1. 기본 패턴과 대규모 데이터

Wu, M. J., Jang, J. S. R., Chen, J. L. (2015). **Wafer Map Failure Pattern Recognition and Similarity Ranking for Large-Scale Data Sets.** IEEE Transactions on Semiconductor Manufacturing, 28(1), 1–12. 온라인 공개 2014년, 권호 발행 2015년.

[DOI](https://doi.org/10.1109/TSM.2014.2364237) · [IEEE](https://ieeexplore.ieee.org/document/6932449/)

확인 범위: 출판사 초록·서지. 회전·크기 변화에 강한 특징과 유사 map 검색을 다룬다. 811,457개 실제 map으로 구성한 공개 데이터의 배경 문헌이다. 형상 분류와 유사 사례 검색에 참고하되 방향 불변 특징과 실제 시계방향 측정은 별도로 유지한다.

### R2. 요청한 Ensemble 리뷰의 원논문

Saqlain, M., Jargalsaikhan, B., Lee, J. Y. (2019). **A Voting Ensemble Classifier for Wafer Map Defect Patterns Identification in Semiconductor Manufacturing.** IEEE Transactions on Semiconductor Manufacturing, 32(2), 171–182.

[DOI](https://doi.org/10.1109/TSM.2019.2904306) · [IEEE](https://ieeexplore.ieee.org/document/8664594/)

확인 범위: 원논문 서지와 공개 초록, 관련 학술논문의 방법 설명. Density·geometry·Radon 계열 특징과 voting ensemble을 이해하는 출발점이다. 전문 전체의 독립 검토는 하지 않았다. 초기 특징 기반 분류를 설계할 때 읽을 우선순위가 높다.

### R3. 특징 기반 모델과 CNN 결합

Kang, H., Kang, S. (2021). **A stacking ensemble classifier with handcrafted and convolutional features for wafer map pattern classification.** Computers in Industry, 129, 103450.

[DOI](https://doi.org/10.1016/j.compind.2021.103450) · [출판사](https://www.sciencedirect.com/science/article/pii/S0166361521000579)

확인 범위: 공개 초록·서론·부분 본문. 사람이 설계한 특징과 CNN이 유형별로 다른 강점을 보인다는 점을 바탕으로 두 분류기의 출력을 결합한다. 기하학적 특징 모델과 CNN을 같은 split에서 비교한 뒤 결합하는 설계에 직접 참고할 수 있다.

### R4. 몰림성을 통계적으로 다루는 연구

Koo, J., Hwang, S. (2021). **A Unified Defect Pattern Analysis of Wafer Maps Using Density-Based Clustering.** IEEE Access, 9, 78873–78882.

[DOI](https://doi.org/10.1109/ACCESS.2021.3084221) · [저자 소속기관 초록](https://pure.seoultech.ac.kr/en/publications/a-unified-defect-pattern-analysis-of-wafer-maps-using-density-bas/) · [대학 저장소 PDF](https://repository.hanyang.ac.kr/bitstream/20.500.11754/192277/1/2021.5_%EA%B5%AC%EC%9E%AC%ED%9B%88_A%20Unified%20Defect%20Pattern%20Analysis%20of%20Wafer%20Maps%20Using%20Density-Based%20Clustering.pdf)

확인 범위: 기관 초록·서지. PDF 검색은 확인했으나 본문 직접 열기는 시간초과. 밀도 기반 군집의 core point를 이용해 공간 무작위성 검정과 군집 분석을 연결한다. 단순히 cluster가 생겼다는 이유만으로 이상으로 선언하지 않는 설계에 참고한다.

### R5. 혼합 패턴 데이터와 다중 label

Wang, J. et al. (2020). **Deformable Convolutional Networks for Efficient Mixed-type Wafer Defect Pattern Recognition.** IEEE Transactions on Semiconductor Manufacturing.

[DOI](https://doi.org/10.1109/TSM.2020.3020985) · [MixedWM38 원저자 데이터·코드](https://github.com/Junliangwangdhu/WaferMap)

확인 범위: 원저자 README. 약 3.8만 개 이상의 map, 정상·단일·혼합을 포함한 38종을 안내한다. 원본 전기적 검사 자료에 GAN 생성 자료를 추가했다. 52×52 배열에서 0=빈 위치, 1=정상 die, 2=불량 die이며 label은 8개 기본 유형의 다중 label 표현이다. README의 one-hot 표현에도 불구하고 혼합형은 여러 label이 활성화되는 의미로 해석해야 한다. Label 수정 이력이 있으므로 데이터 버전을 기록한다. Inspection dot map에 대한 직접 성능 검증 자료는 아니다.

### R6. 분류와 분할을 함께 수행하는 모델

Nag, S. et al. (2022). **WaferSegClassNet: A Light-weight Network for Classification and Segmentation of Semiconductor Wafer Defects.**

[공개 저자 원고](https://arxiv.org/abs/2207.00960) · [저자 코드](https://github.com/ckmvigil/WaferSegClassNet) · [출판사](https://www.sciencedirect.com/science/article/abs/pii/S0166361522001178)

확인 범위: 공개 초록. Shared encoder를 사용한 분류·segmentation 결합을 다룬다. 위치 표시까지 확장할 때의 모델 구조 참고 자료다. 논문에서 말하는 segmentation의 label 정의가 ‘각 패턴의 개별 분리’까지 제공하는지 확인한 뒤 요구사항과 맞춰야 한다.

### R7. 혼합 패턴의 영역 분리에 가까운 후속 연구

Kwon, D. et al. (2026). **SePArate: Segmenting Patterns from Defects in Wafer Manufacturing Using Weak Supervision.** 공개 원고에 DAC 2026 및 DOI가 표기되어 있다.

[공개 원고](https://arxiv.org/html/2608.30410v1) · [DOI](https://doi.org/10.1145/3770743.3804046) · [저자 코드](https://github.com/meowrowan/SePArate)

확인 범위: 공개 본문. Image 수준 label에서 혼합 패턴별 pixel 영역을 학습하는 방법이다. MixedWM38와 DRAM mat 수준 자료를 평가한다. ‘유형이 무엇인가’에서 ‘어느 점이 어느 패턴에 속하는가’로 확장할 때 우선 검토할 자료다. 자체 dot map 및 bin별 집계 요구에 대한 재검증은 필요하다. 원고는 2026년 8월 31일 공개되어 이번 조사일 기준 이용 가능하다.

### R8. 국내 논문: 신규 패턴 판정

송창용·정영선·김병훈 (2022). **Multi-class Data Description 기반의 웨이퍼 빈 맵 불량 패턴 분류 및 신규 불량 패턴 검출방법.** 대한산업공학회지, 48(3), 298–309.

[공개 본문](https://jkiie.org/_PR/view/?aidx=33271&bidx=2964) · [DOI](https://doi.org/10.7232/JKIIE.2022.48.3.298)

확인 범위: 공개 본문. CNN 특징과 class별 영역에 대한 거리로 기존 유형 분류와 새로운 유형 검출을 함께 다룬다. 모든 map을 기존 class 중 하나로 강제 배정하지 않는 운영 설계에 참고한다. 논문의 noise 제거 정책은 분석 목적에 따른 선택이며, inspection에서 희박한 실제 defect를 삭제하는 규칙으로 그대로 가져오지 않는다.

### R9. 요청한 ViT 데이터 증강 논문

Fan, S. K. S., Chiu, S. H. (2024). **A new ViT-Based augmentation framework for wafer map defect classification to enhance the resilience of semiconductor supply chains.** International Journal of Production Economics, 273, 109275.

[DOI](https://doi.org/10.1016/j.ijpe.2024.109275) · [출판사](https://www.sciencedirect.com/science/article/pii/S0925527324001324) · [소속기관 공개 초록](https://ntut.elsevierpure.com/en/publications/a-new-vit-based-augmentation-framework-for-wafer-map-defect-class/)

확인 범위: 소속기관 초록·서지. ViT 기반 증강을 통해 class 불균형을 완화하고 CNN의 결함 분류를 개선하는 연구다. 소수 유형의 데이터 증강 단계에 참고한다. 전문을 확보하지 않았으므로 세부 구현·재현 성능을 확인했다고 주장하지 않는다.

### R10. 요청한 국내 CNN·MLP 비교 연구

백선재·이민혁 (2022). **딥러닝을 활용한 반도체 웨이퍼 불량 유형 구분 모델에 관한 연구.** 한국통신학회 동계종합학술발표회 논문집, 1158–1159.

[원논문 서지·접근 페이지](https://www.dbpia.co.kr/journal/articleDetail?nodeId=NODE11047926) · [사용자 지정 리뷰](https://sonstory.tistory.com/26)

확인 범위: 원논문 서지 확인. 원문 전체를 읽지 않았으므로 블로그의 성능 수치를 검증된 사실로 재인용하지 않았다. 국내 입문 자료로 두되 운영 설계 근거는 공개 원문을 함께 확인할 수 있는 위 논문들로 보완한다.

### R11. 공개 전문으로 읽을 수 있는 Ensemble 후속 연구

Choi, J., Suh, D., Otto, M. (2023). **Boosted Stacking Ensemble Machine Learning Method for Wafer Map Pattern Classification.** Computers, Materials & Continua, 74(2), 2945–2966.

[공개 본문](https://www.techscience.com/cmc/v74n2/50296/html) · [DOI](https://doi.org/10.32604/cmc.2023.033417)

확인 범위: 공개 본문·초록. 데이터 증강과 stacking을 결합한 분류 연구다. 기본 특징 기반 모델 이후 ensemble 실험을 설계할 때 활용한다. 웹페이지의 선공개 날짜는 2022년이며 권호의 서지 연도는 2023년이다.

## 11. 제공 링크의 확인 결과와 구현 문서

Google 공유 링크는 장기 지식 파일의 주 링크로 사용하지 않고 제목이 일치하는 원문 주소를 찾아 병기했다. 아래 블로그는 제공 자료 추적용이며 기술적 권고의 근거는 논문·공식 문서를 사용했다.

| 제공 자료 | 직접 링크와 확인 상태 |
|---|---|
| Tensor 변환 글 | [원문](https://anweh.tistory.com/10), 내용 확인. 아래 PyTorch 공식 문서로 보완 |
| 성균관대 공정경로 프로젝트 | [연구실 프로젝트](https://qe.skku.edu/bbs/board.php?bo_table=projects&device=pc&page=1&wr_id=12), 제목·검색에 노출된 개요 확인. 직접 페이지는 일시 오류. 알고리즘 전문을 확인한 상태는 아님 |
| ViT 논문 | R9로 연결. 기관 초록 확인 |
| Ensemble 리뷰 | [원문](https://aiegg-travel.tistory.com/entry/Ensemble-%EB%AA%A8%EB%8D%B8%EB%A1%9C-Wafer-Map-Defect-Pattern-%EB%B6%84%EB%A5%98%ED%95%98%EA%B8%B0-%EB%85%BC%EB%AC%B8-%EB%A6%AC%EB%B7%B0), 리뷰 대상은 R2임을 확인 |
| 국내 딥러닝 리뷰 | [원문](https://sonstory.tistory.com/26), R10의 서지 확인 |

| ID | 공식 문서 | 적용 대상 |
|---|---|---|
| T1 | [PyTorch ToImage](https://docs.pytorch.org/vision/stable/generated/torchvision.transforms.v2.ToImage.html) | 영상에서 tensor 표현으로 변환 |
| T2 | [PyTorch ToDtype](https://docs.pytorch.org/vision/stable/generated/torchvision.transforms.v2.ToDtype.html) | dtype·영상값 scale 처리 |
| T3 | [OpenCV inRange](https://docs.opencv.org/4.x/da/d97/tutorial_threshold_inRange.html) | 색상 범위 분리 |
| T4 | [OpenCV Shape Analysis](https://docs.opencv.org/4.13.0/d3/dc0/group__imgproc__shape.html) | 연결요소·중심·통계 |
| T5 | [OpenCV Hough Lines](https://docs.opencv.org/4.x/d9/db0/tutorial_hough_lines.html) | 직선 후보 추출 |
| T6 | [scikit-learn DBSCAN](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.DBSCAN.html) | 밀도 기반 군집 |

권장 읽기 순서는 R4 → R2 → R3 → R8이다. 위치별 혼합 패턴 분리가 필요하면 R5 → R6 → R7을 추가하고, 소수 class가 문제일 때 R9를 검토한다. 논문 간 정확도 수치는 데이터 구성·class 수·분할 방식이 달라 직접 순위를 매기지 않는다.

## 12. 구현을 구체화할 최소 자료

1. 동일 표시 방식의 대표 map 이미지와 화면 기준 방향 설명.
2. 가능한 경우 동일 map의 defect X·Y·classification bin export.
3. Bin 번호의 의미와 집계표가 전체·필터·sampling 중 무엇을 의미하는지.
4. 검사 영역·제외 영역 또는 검사 die 목록.
5. 환형·선형·몰림성·혼합·정상 참고 사례의 정답 의견.

자료를 확보하면 첫 검증 목표는 ‘원본에서 불량 위치가 정확히 추출되고 sector·bin별 집계가 맞는가’로 둔다. 이 결과를 확인한 뒤 패턴 분류 모델의 성능을 평가한다.
