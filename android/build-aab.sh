#!/usr/bin/env bash
# Play Console 업로드용 AAB 빌드.
#
# APK 빌드와 다른 점은 두 가지뿐이다.
#   1) aapt2 link에 --proto-format — AAB는 바이너리가 아닌 protobuf 리소스를 쓴다
#   2) 결과물을 bundletool이 요구하는 디렉터리 구조로 재배치한 뒤 build-bundle
# 서명은 업로드 키로만 한다. 배포 서명은 Play 앱 서명이 대신 해 주므로
# 키를 잃어버려도 앱이 죽지 않는다 — 사이드로드 APK와 결정적으로 다른 점이다.
set -euo pipefail

: "${ANDROID_HOME:?ANDROID_HOME을 설정하세요}"
: "${BUNDLETOOL:?bundletool jar 경로를 BUNDLETOOL로 설정하세요}"
BT="${ANDROID_HOME}/build-tools/34.0.0"
PLAT="${ANDROID_HOME}/platforms/android-35/android.jar"
KS="${KEYSTORE:-upload.keystore}"
KS_PASS="${KEYSTORE_PASS:?KEYSTORE_PASS 환경변수로 키스토어 비밀번호를 넘기세요}"
ALIAS="${KEY_ALIAS:-upload}"
OUT="../release/market-heatmap-1.0.aab"

rm -rf aab && mkdir -p aab/gen aab/classes aab/dex aab/base

echo "[1/6] 리소스 컴파일"
"$BT/aapt2" compile --dir res -o aab/resources.zip

echo "[2/6] proto 포맷으로 링크 (AAB 필수)"
"$BT/aapt2" link --proto-format -o aab/linked.apk -I "$PLAT" \
  --manifest AndroidManifest.xml --java aab/gen \
  --min-sdk-version 24 --target-sdk-version 35 aab/resources.zip

echo "[3/6] 자바 컴파일 · dex"
javac -encoding UTF-8 -source 8 -target 8 -nowarn \
  -bootclasspath "$PLAT" -classpath "$PLAT" -d aab/classes \
  aab/gen/com/jinhae/heatmap/R.java src/com/jinhae/heatmap/MainActivity.java
"$BT/d8" --lib "$PLAT" --min-api 24 --output aab/dex $(find aab/classes -name '*.class')

echo "[4/6] 번들 구조 재배치"
(cd aab && unzip -qo linked.apk -d extracted)
mkdir -p aab/base/manifest aab/base/dex
mv aab/extracted/AndroidManifest.xml aab/base/manifest/AndroidManifest.xml
mv aab/extracted/resources.pb aab/base/resources.pb
[ -d aab/extracted/res ] && mv aab/extracted/res aab/base/res
cp aab/dex/classes.dex aab/base/dex/classes.dex
(cd aab/base && zip -qr ../base.zip manifest res resources.pb dex)

echo "[5/6] 번들 생성"
java -jar "$BUNDLETOOL" build-bundle --modules=aab/base.zip --output=aab/app.aab --overwrite

echo "[6/6] 업로드 키 서명"
if [ ! -f "$KS" ]; then
  keytool -genkeypair -keystore "$KS" -storepass "$KS_PASS" -keypass "$KS_PASS" \
    -alias "$ALIAS" -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Market Heatmap Upload, OU=Personal, O=jinhae8971, L=Seoul, C=KR"
  echo "  업로드 키스토어 생성: $KS  ← 반드시 백업하세요"
fi
mkdir -p ../release
cp aab/app.aab "$OUT"
jarsigner -keystore "$KS" -storepass "$KS_PASS" -keypass "$KS_PASS" \
  -sigalg SHA256withRSA -digestalg SHA-256 "$OUT" "$ALIAS" > /dev/null
jarsigner -verify "$OUT" | head -1

echo "완료: $OUT"
