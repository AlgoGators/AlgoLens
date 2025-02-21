from setuptools import setup, find_packages

# Read the requirements from requirements.txt
with open("requirements.txt") as f:
    requirements = f.read().splitlines()

setup(
    name='AlgoLens',
    version='0.1',
    packages=find_packages(),
    py_modules=['cli'],
    install_requires=requirements,  # This will install dependencies from requirements.txt
    entry_points={
        'console_scripts': [
            'algolens=cli:main',
        ],
    },
)
