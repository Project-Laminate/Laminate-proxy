#!/usr/bin/env python
"""
Setup script for the DICOM Receiver package
"""

from setuptools import setup, find_packages
import os
import re

# Get the version from dicom_receiver/__init__.py
with open(os.path.join('dicom_receiver', '__init__.py'), 'r') as f:
    version_file = f.read()
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", version_file, re.M)
    if version_match:
        version = version_match.group(1)
    else:
        raise RuntimeError("Unable to find version string in dicom_receiver/__init__.py")

# Read the README file for the long description
with open('README.md', 'r') as f:
    long_description = f.read()

setup(
    name='dicom_receiver',
    version=version,
    description='A secure DICOM receiver service for hospital use with API integration',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Hospital IT Team',
    author_email='it@hospital.example',
    url='https://github.com/hospital/dicom-receiver',
    packages=find_packages(),
    scripts=[
        'scripts/dicom_receiver_start.py',
        'scripts/restore_dicom_info.py',
        'scripts/dicom_config.py',
        'scripts/upload_study.py',
    ],
    entry_points={
        'console_scripts': [
            'dicom-receiver=dicom_receiver.cli.receiver:main',
            'dicom-restore=dicom_receiver.cli.restore:main',
            'dicom-config=dicom_receiver.config:print_config',
            'dicom-upload=scripts.upload_study:main',
        ],
    },
    install_requires=[
        'pynetdicom>=2.1.0',
        'pydicom>=2.4.0',
        'cryptography>=44.0.0',
        'requests>=2.30.0',
    ],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Healthcare Industry',
        'Topic :: Scientific/Engineering :: Medical Science Apps.',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Environment :: Console',
        'Intended Audience :: Healthcare Industry',
        'Intended Audience :: Information Technology',
        'Topic :: Communications',
        'Topic :: Scientific/Engineering :: Medical Science Apps.',
    ],
    python_requires='>=3.7',
    keywords='dicom, medical imaging, healthcare, encryption, api',
    project_urls={
        'Documentation': 'https://github.com/hospital/dicom-receiver',
        'Source': 'https://github.com/hospital/dicom-receiver',
        'Issue Tracker': 'https://github.com/hospital/dicom-receiver/issues',
    },
) 