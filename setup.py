# setup.py
from pathlib import Path
from setuptools import setup, find_packages

README = Path(__file__).with_name("README.md")
long_description = README.read_text(encoding="utf-8") if README.exists() else ""

setup(
    name="outexplain-cli",
    version="1.0.9",
    description="Explain the output of your last terminal command, right in the terminal.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Skyresth/outexplain",
    author="Skyresth",
    author_email="talesgalilea@outlook.com",
    license="MIT",
    packages=find_packages(exclude=("tests", "tests.*", "examples", "example*")),
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "outexplain = outexplain.outexplain:main",
        ]
    },
    install_requires=[
        "openai>=1.30",
        "anthropic>=0.34",
        "ollama>=0.3",
        "rich>=13.7",
        "psutil>=5.9",
    ],
    python_requires=">=3.10",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Topic :: Software Development",
        "Topic :: Software Development :: Debuggers",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    keywords=(
        "openai anthropic ollama cli terminal logs errors stacktrace explain debugging"
    ),
    project_urls={
        "Source": "https://github.com/Skyresth/outexplain",
        "Issues": "https://github.com/Skyresth/outexplain/issues",
    },
)
