from setuptools import setup, find_packages

setup(
    name="moomoo-dashboard",
    version="0.1.0",
    description="Claude Code skill for visual equity research reports powered by MooMoo OpenAPI",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
)
