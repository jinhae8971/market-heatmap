#!/usr/bin/env bash
# APK 빌드 — Gradle 없이 Android SDK 도구만 직접 호출한다.
#
# Gradle을 쓰지 않는 이유: 이 앱은 액티비티 하나에 외부 의존성이 0개다.
# AGP를 끌어오면 빌드가 수백 MB·수 분으로 불어나는데 얻는 게 없다.
# 여기서는 aapt2 → javac → d8 → zipalign → apksigner 다섯 단계가 전부다.
set -euo pipefail

: "${ANDROID_HOME:?ANDROID_HOME을 Android SDK 경로로 설정하세요}"
BT="${ANDROID_HOME}/build-tools/34.0.0"
PLAT="${ANDROID_HOME}/platforms/android-35/android.jar"
KS="${KEYSTORE:-build/heatmap.keystore}"
KS_PASS="${KEYSTORE_PASS:-heatmap2026}"
ALIAS="${KEY_ALIAS:-heatmap}"
OUT="build/market-heatmap-1.0.apk"

rm -rf build
mkdir -p build/classes build/dex build/gen

echo "[1/5] 리소스 컴파일"
"$BT/aapt2" compile --dir res -o build/resources.zip

echo "[2/5] 리소스 링크"
"$BT/aapt2" link -o build/base.apk -I "$PLAT" --manifest AndroidManifest.xml \
  --java build/gen --min-sdk-version 24 --target-sdk-version 35 build/resources.zip

echo "[3/5] 자바 컴파일"
# -encoding UTF-8 필수: 한글 문자열 리소스가 R.java 주석으로 들어간다
javac -encoding UTF-8 -source 8 -target 8 -nowarn \
  -bootclasspath "$PLAT" -classpath "$PLAT" -d build/classes \
  build/gen/com/jinhae/heatmap/R.java src/com/jinhae/heatmap/MainActivity.java

echo "[4/5] dex 변환"
# 람다를 쓰면 desugaring이 필요해 d8이 metafactory를 찾지 못한다.
# 소스에서 익명 클래스를 쓰는 이유가 이것이다.
"$BT/d8" --lib "$PLAT" --min-api 24 --output build/dex \
  $(find build/classes -name '*.class')

echo "[5/5] 패키징 · 서명"
cp build/base.apk build/unsigned.apk
(cd build/dex && zip -q ../unsigned.apk classes.dex)
"$BT/zipalign" -f -p 4 build/unsigned.apk build/aligned.apk

if [ ! -f "$KS" ]; then
  echo "  키스토어 생성: $KS"
  keytool -genkeypair -keystore "$KS" -storepass "$KS_PASS" -keypass "$KS_PASS" \
    -alias "$ALIAS" -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Market Heatmap, OU=Personal, O=jinhae8971, L=Seoul, C=KR"
fi

"$BT/apksigner" sign --ks "$KS" --ks-pass "pass:$KS_PASS" \
  --key-pass "pass:$KS_PASS" --ks-key-alias "$ALIAS" --out "$OUT" build/aligned.apk
"$BT/apksigner" verify --print-certs "$OUT" | head -2

echo "완료: $OUT"
