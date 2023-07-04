# OAI API Checker
Program that allows you to check all the available information about your OAI API key

Basically, you put in one or an array of keys and the program analyzes them for you.

It prints out if the key is glitched (detects most glitched keys with very high accuracy), if gpt-4 is accessible and lots of other info, including key limits, usage, and expiration date. It will also store the gpt-4, glitched and valid keys in their respective .txt files in the folder where you run the program.

Program works really fast (was able to process 22k keys in less than 3 minutes) and reliable. Just in case, the program will generate a .log file where all debug info will be stored. Feel free to send them to me in case of bugs and errors (buhankoanon@proton.me).

In this repository, you can find a a link to compiled .exe file of the program (all necessary libraries included), as well as a source Python code.

In order to run the source Python code, you will need Python, pip and modules such as openai, requests, colorama.

There is now also code for Discord bot available (discontinued). You can add it to your secret club and check keys all you want.

UPD:

Moved the .exe file into the separate storage drive (Proton Drive). Now you can download it from here:

OAI_API_Checker.exe - https://drive.proton.me/urls/4T2QGJFBGM#fW0YsN9WskCG