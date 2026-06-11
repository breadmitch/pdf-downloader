# Build Instructions for Windows

These are the simple steps to turn the Python script into a Windows `.exe`.

## 1. Install Python

Install Python 3.10 or newer from the official Python website.

During installation, make sure to check:

```text
Add Python to PATH
```

## 2. Open Command Prompt

Press Start, type:

```text
cmd
```

Then open Command Prompt.

## 3. Go to the project folder

Example:

```bat
cd C:\Users\Mitch\Desktop\mining-report-pdf-downloader
```

Adjust the path if you put the folder somewhere else.

## 4. Create a virtual environment

```bat
py -m venv .venv
```

Activate it:

```bat
.venv\Scripts\activate
```

## 5. Install dependencies

```bat
pip install -r requirements.txt
```

## 6. Test the app before packaging

```bat
python app.py
```

Make sure the window opens before continuing.

## 7. Install PyInstaller

```bat
pip install pyinstaller
```

## 8. Build the Windows app

```bat
pyinstaller --onefile --windowed --name "Mining Report PDF Downloader" app.py
```

## 9. Find the finished app

The finished app will be here:

```text
dist\Mining Report PDF Downloader.exe
```

That `.exe` is the file you can send to someone or attach to a GitHub release.

## 10. Optional cleanup

PyInstaller creates temporary folders named `build` and `dist`, plus a `.spec` file.

Keep `dist\Mining Report PDF Downloader.exe`.

You can delete `build` if you want.
