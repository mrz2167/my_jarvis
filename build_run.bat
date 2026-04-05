@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64

set CMAKE_EXE=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe
set NINJA_EXE=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe

cd /d C:\Projects\my_jarvis\core

"%CMAKE_EXE%" -B build -G Ninja "-DCMAKE_MAKE_PROGRAM=%NINJA_EXE%" > C:\Projects\my_jarvis\cmake_out.txt 2>&1
echo CMAKE_EXIT=%ERRORLEVEL% >> C:\Projects\my_jarvis\cmake_out.txt

"%CMAKE_EXE%" --build build >> C:\Projects\my_jarvis\cmake_out.txt 2>&1
echo BUILD_EXIT=%ERRORLEVEL% >> C:\Projects\my_jarvis\cmake_out.txt
