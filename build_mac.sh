#!/bin/bash
# Build Sourceter.app — run this on a Mac, inside the activated venv.
set -e
python -m pip install --upgrade pyinstaller pillow
python make_icon.py
pyinstaller --noconfirm --clean \
    --windowed \
    --name Sourceter \
    --icon icon.png \
    --osx-bundle-identifier com.sourceter.app \
    app.py

# strip the quarantine flag so Gatekeeper doesn't fight the first launch
xattr -cr dist/Sourceter.app || true

cd dist && zip -qry Sourceter-mac.zip Sourceter.app && cd ..
echo
echo "Done. dist/Sourceter.app  (and dist/Sourceter-mac.zip to send)"
