#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "torchcodec macOS rpath patch is only needed on macOS."
  exit 0
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required to locate ffmpeg. Install ffmpeg first: brew install ffmpeg" >&2
  exit 1
fi

FFMPEG_LIB="${FFMPEG_LIB:-$(brew --prefix ffmpeg)/lib}"
PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

if [[ ! -d "$FFMPEG_LIB" ]]; then
  echo "FFmpeg library directory was not found: $FFMPEG_LIB" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python executable was not found: $PYTHON_BIN" >&2
  exit 1
fi

TORCHCODEC_DIR="$("$PYTHON_BIN" -c 'import importlib.util; spec = importlib.util.find_spec("torchcodec"); print(next(iter(spec.submodule_search_locations), "") if spec and spec.submodule_search_locations else "")')"

if [[ -z "$TORCHCODEC_DIR" || ! -d "$TORCHCODEC_DIR" ]]; then
  echo "torchcodec is not installed in this environment."
  exit 0
fi

patched=0
while IFS= read -r -d '' library; do
  if ! otool -l "$library" | grep -Fq "$FFMPEG_LIB"; then
    install_name_tool -add_rpath "$FFMPEG_LIB" "$library"
    patched=1
  fi
  codesign --force --sign - "$library" >/dev/null 2>&1
done < <(find "$TORCHCODEC_DIR" -maxdepth 1 \( -name 'libtorchcodec_*.dylib' -o -name 'libtorchcodec_*.so' \) -print0)

"$PYTHON_BIN" -c 'import importlib.metadata as metadata; import torchcodec; print("torchcodec " + metadata.version("torchcodec") + " is loadable")'

if [[ "$patched" == "1" ]]; then
  echo "Patched torchcodec rpaths to use $FFMPEG_LIB."
else
  echo "torchcodec rpaths already include $FFMPEG_LIB."
fi
