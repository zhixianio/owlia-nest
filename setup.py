from setuptools import setup, find_packages

setup(
    name="owlia-nest",
    version="0.1.1",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    package_data={"owlia_nest": ["icons/*"]},
    include_package_data=True,
    install_requires=["markdown>=3.4", "pygments>=2.15"],
    entry_points={
        "console_scripts": ["owlia-nest=owlia_nest.cli:main"],
    },
    python_requires=">=3.9",
)
