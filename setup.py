from setuptools import find_packages, setup

setup(
    name="ubio_autobox",
    packages=find_packages(exclude=["ubio_autobox_tests"]),
    install_requires=["dagster", "dagster-cloud"],
    extras_require={"dev": ["dagster-webserver", "pytest"]},
)
