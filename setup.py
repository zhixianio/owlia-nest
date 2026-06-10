import re
from setuptools import setup, find_packages

# Read version from pyproject.toml to avoid duplication
try:
    with open("pyproject.toml") as f:
        m = re.search(r'version\s*=\s*"([^"]+)"', f.read())
    version = m.group(1) if m else "0.1.0"
except Exception:
    version = "0.1.0"

setup(
    name="owlia-nest",
    version=version,
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    package_data={"owlia_nest": ["icons/*", "static/*"]},
    include_package_data=True,
    install_requires=["markdown>=3.4", "pygments>=2.15"],
    entry_points={
        "console_scripts": ["owlia-nest=owlia_nest.cli:main"],
    },
    python_requires=">=3.9",
)
