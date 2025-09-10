# ANUBIS: Automated Vial Weighing Platform

## Overview

This repository contains the software for automating the process of vial weighing using the **ANUBIS** robotic arm platform at Calico. The goal of this project is to increase throughput, improve accuracy, and reduce the manual effort involved in weighing large numbers of vials (e.g., in Micronic racks) for various experimental assays.

We are open-sourcing this project with the hope that it can be a useful reference or a starting point for other labs looking to implement similar automation solutions.

This project was developed by Perry Azougi in 2025 as part of his summer internship in the Lab Automation group at Calico Lifesciences LLC, with contributions from Elliot Mount, Andre Nguyen, David Conegliano, and Robert Keyser.


## Features

This project is in its early stages, but it includes the following features:

- A fully automated workflow for taring and weighing vials.
- Recording of weight data associated with vial identifiers.
- Routines for detecting and handling common errors (e.g., vial drops, balance instability).

## Getting Started

### Prerequisites

This software is developed for the ANUBIS robotic platform. The intended hardware components are:

- Meca500 six-axis industrial robotic arm
- Analytical balance (e.g., Mettler Toledo, Sartorius) with a serial/Ethernet interface
- Vial racks and corresponding nests

To run the application or build the executable, you'll need **Python** (version 3.8 or higher) and the following dependency:

```bash
pip install pyinstaller
```

### Installation

To get a copy of the current code, clone the repository:

```bash
git clone https://github.com/calico/calicolabs-auto-anubis-vialweighing.git
cd calicolabs-auto-anubis-vialweighing
```

## Usage

### Running the Application

To run the application directly from the source code, navigate to the project directory and execute the main Python script:

```bash
python "ANUBIS Code/Current code/ANUBIS_V.W.WC_v2.8.py"
```

### Building the Executable

The application can also be packaged as a standalone executable using `PyInstaller`. This creates a single file that can be run on a lab computer without needing a Python environment. To build the executable, run the following command in your terminal:

```bash
# For a GUI application, to bundle into one file and hide the console window
pyinstaller --onefile --windowed "ANUBIS Code/Current code/ANUBIS_V.W.WC_v2.8.py"
```

After the build process, the executable will be located in the `dist/` folder.
