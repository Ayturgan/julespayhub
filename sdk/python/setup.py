#!/usr/bin/env python3

from setuptools import setup, find_packages
import os

# Читаем README для long_description
def read_readme():
    try:
        with open('README.md', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return 'QRPayHub Python SDK for bank integration'

# Читаем requirements
def read_requirements():
    try:
        with open('requirements.txt', 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except FileNotFoundError:
        return ['requests>=2.25.0']

setup(
    name='qrpayhub-sdk',
    version='1.0.0',
    description='Official Python SDK for QRPayHub API integration',
    long_description=read_readme(),
    long_description_content_type='text/markdown',
    author='QRPayHub Team',
    author_email='integration@qrpayhub.com',
    url='https://github.com/qrpayhub/python-sdk',
    project_urls={
        'Documentation': 'https://docs.qrpayhub.com',
        'Source': 'https://github.com/qrpayhub/python-sdk',
        'Tracker': 'https://github.com/qrpayhub/python-sdk/issues',
    },
    packages=find_packages(exclude=['tests*', 'examples*']),
    python_requires='>=3.7',
    install_requires=read_requirements(),
    extras_require={
        'dev': [
            'pytest>=6.0',
            'pytest-cov>=2.0',
            'black>=21.0',
            'isort>=5.0',
            'flake8>=3.8',
            'mypy>=0.812',
            'requests-mock>=1.8',
        ],
        'async': [
            'aiohttp>=3.7.0',
        ]
    },
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Office/Business :: Financial',
    ],
    keywords='qrpayhub payment qr sdk banking fintech',
    include_package_data=True,
    zip_safe=False,
    entry_points={
        'console_scripts': [
            'qrpayhub-test=qrpayhub_sdk.cli:main',
        ],
    },
)
