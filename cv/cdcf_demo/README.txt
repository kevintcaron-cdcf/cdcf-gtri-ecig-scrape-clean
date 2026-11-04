**** Iced Vape Juice Pipeline ****

This file outlines the scripts needed to produce VLM results for vape juice images.

vlm_env.yml - this file contains the conda enviroment used to run these scripts


- Step 1: Data Setup
These scripts expect images scraped from websites along with a csv of product links.
The images from a single website should be in a single folder.


- Step 2: YOLO Detections
The first script to be used is yolo_detections.py, this will run predictions on all
images scraped to identify those that contain vape juices. The images will then be seperated
such that the juice images will be in a folder designated with "_clean".

This script requires that you provide a file argument, which is the location of the images:
ex: python yolo_detections.py -f vapewh_images


- Step 3: Google Gemini Predictions
The second script to be used is google_gemini_predictions.py, this will run VLM predictions
on all images that were identified as containing a vape juice. The resulting predictions will be put into a text file designated with "_gemini_predictions_".

This script requires you provide a few arguments

-f is a file argument, the name of the dataset
-k is your google gemini API key
-s is your starting index of images to be run (only 200 images can be run at once)
-e is the ending index of images to be run (only 200 images can be run at once)

ex: python google_gemini_predictions.py -f vapewh_images -k "$GOOGLE_GEMINI_API_KEY" -s 0 -e 100




