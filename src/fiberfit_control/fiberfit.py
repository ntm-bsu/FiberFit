#!/usr/local/bin/python3

"""This is a control part of the GUI application"""

"3rd party imports: "
import pathlib
import sys
import datetime
import matplotlib
import threading
import time
matplotlib.use("Qt5Agg")  # forces to use Qt5Agg so that Backends work
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from PyQt5 import QtWidgets
from PyQt5.Qt import *
from PyQt5.QtWidgets import QFileDialog  # In order to select a file
from orderedset import OrderedSet
import base64
from PyQt5.QtCore import pyqtSlot, pyqtSignal
import os
from PyQt5.QtWidgets import QDesktopWidget
import random
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt
import shutil

"custom file imports"
from src.fiberfit_gui import fiberfit_GUI
from src.fiberfit_model import computerVision_BP
from src.fiberfit_control.support import img_model
from src.fiberfit_control.support import settings
from src.fiberfit_control.support import error
from src.fiberfit_control.support import report

class fft_mainWindow(fiberfit_GUI.Ui_MainWindow, QtWidgets.QMainWindow):
    """Controller part of the application.

    This class is reponsible for gluing parts from the model and gui together. It calls computerVision_BP
    functions to analyze images passed from the user.

    Utilizes various PyQt5 libraries to make a gui. Uses src.fiberfit_gui.fiberfity_GUI code to create its ui.

    Attributes:
        signals:
            go_export: sends an img_model to src.fiberfit_control.support.report
            go_run: signals starting of the thread
            go_update: signals to update labels and populate combo box
            send_data_to_report: sends data to src.fiberfit_control.support_report
            go_process_iamges: signals to do final touches after image was processed by the computerVision_BP
            send_error: signals that something went wrong
        vars:
            dataList: contains a list of already processed images. helps src.fiberfit_control.support.report remember
                which images have already been processed.
            screenDim: (w,h) of the screen
            dpi: dots-per-inch of the screen
            selected_files: target files that user selected
            current_index: index of currently selected image
            settings_browser: a settings QDialog
            error_browser: error QDialog
            runtime: measures time taken to perform computerVision_BP
            is_resized: indicates if user already resized image to his/her preference
            is_started: shows whether program analyzed an image already or not
            run_counter: how many rounds the program ran (useful when needed to name saved png images)
    """

    go_export = pyqtSignal(img_model.ImgModel)
    go_run = pyqtSignal()
    # Args: int index of the image in the imgList
    go_update = pyqtSignal(int)
    # Args: list of currently processed images, data list from the report.py, list of all the images (both processed
    # currently and in the past), u_cut, l_cut, rad_step, angle_inc
    send_data_to_report = pyqtSignal(list, list, OrderedSet, float, float, float, float)
    # Args: number of images to be processed, the most recent processed image, list of currently processed images,
    # 1/0 whether processed images was the last one or not, running time, number indicating order of the image.
    go_process_images = pyqtSignal(int, img_model.ImgModel, list, int, int, int)
    # Args: list of names of the files to be processed, number indicating order of the image (useful when indexing to the
    # name of the file), 1/0 depending on what type of error occured.
    send_error = pyqtSignal(list, int, int)

    def __init__(self, Parent=None):
        """
        Initializes all instance variables a.k.a attributes of a class.
        """
        super(fft_mainWindow, self).__init__()
        self.imgList = OrderedSet()
        # Stuff I looked at
        self.screenDim, self.dpi = self.receiveDim()
        self.setupUi(self, self.screenDim.height(), self.screenDim.width())
        self.dataList = []
        self.selected_files = []
        self.current_index = 0
        self.runtime = 0
        self.is_resized = False
        self.is_started = False
        self.saved_images_dir_name = ''
        self.run_counter = 0  # I need it to be able to process multiple images.
        self.settingsBrowser = settings.SettingsWindow(self, self.screenDim)
        self.errorBrowser = error.ErrorDialog(self, self.screenDim)
        self.report_dialog = report.ReportDialog(self, self, self.screenDim)

        # model settings
        self.u_cut = float(self.settingsBrowser.ttopField.text())
        self.l_cut = float(self.settingsBrowser.tbottomField.text())
        self.angle_inc = float(self.settingsBrowser.btopField.text())
        self.rad_step = float(self.settingsBrowser.bbottomField.text())

        self.img_canvas = None
        self.log_scl_canvas = None
        self.ang_dist_canvas = None
        self.cart_dist_canvas = None

        self.connect_signals_to_slots()

    @pyqtSlot(list, int, int)
    def handleError(self, files, index, identifier):
        if identifier == 0:
            self.errorBrowser.label.setText("""ERROR:
            Sorry, unfortunately, this file - {name} can not be processed.
            Please make sure that the image has 8-bit image depth,or, equivalently, gray color space and verify that you are using one of the approved file formats: pdf, png, tif, gif, or bmp."""
                                            .format(name=files[index]))
        elif identifier == 1:
            self.errorBrowser.label.setText("""ERROR:
Sorry, unfortunately, the setting you selected are out of input domain for FiberFit.
Please go back to "Settings" and change some values.
            """
                                            )
        else:
            self.errorBrowser.label.setText("""ERROR:

            Sorry, unforutnately, this file - {name} can not be processed.

            Please make sure that the image is square. """.format(name=files[index]))
        self.errorBrowser.show()
        self.progressBar.hide()

    def runner(self):
        """
        Starts a thread that does the heavy-lifting computerVision algorithm
        :return: none
        """
        pThread = myThread(self.go_process_images, self.send_error, self.progressBar, self.saved_images_dir_name, self.run_counter)
        pThread.update_values(self.u_cut, self.l_cut, self.angle_inc, self.rad_step, self.screenDim, self.dpi, self.selected_files)
        if len(self.selected_files) != 0:
            self.progressBar.show()
            self.progressBar.setValue(0)
        pThread.start()

    @pyqtSlot()
    def export(self):
        """
        Function that signals to show the report.
        """
        if (self.is_started):
            self.go_export.emit(self.imgList[self.current_index % len(self.selected_files)])

    def coeff_labels_set_text(self, text, num = None):
        if num is not None:
            self.setupLabels(num)
        else:
            self.kLabel.setText("k = " + text)
            self.muLabel.setText("μ =  " + text)
            self.RLabel.setText(('R' + u"\u00B2") + " = " + text)
            self.sigLabel.setText("σ = " + text)

    def clear(self):
        """
        Clears out canvas.
        """
        if (self.is_started):
            self.coeff_labels_set_text(text="", num=None)
            # clears canvas
            self.cleanCanvas()
            self.progressBar.hide()
            self.selected_files.clear()
            # clears combo-box
            self.selectImgBox.clear()
            # resets isStarted
            self.is_started = False
            self.dataList.clear()
            # empties all images
            self.imgList.clear()
            # resets current index
            self.current_index = 0
            shutil.rmtree(self.saved_images_dir_name)
            self.saved_images_dir_name = ''
            self.run_counter = 0

    def launch(self):
        """
        Allows user to select image to use.
        """
        if self.saved_images_dir_name == '':
            self.create_temp_dir()
        self.selected_files = []
        dialog = QFileDialog()
        filenames = dialog.getOpenFileNames(self, '', None)  # creates a list of fileNames
        for name in filenames[0]:
            self.selected_files.append(pathlib.Path(name))
        self.progressBar.setMaximum(len(filenames[0]))
        #self.currentIndex = 0
        self.go_run.emit()

    @pyqtSlot(int, img_model.ImgModel, list, int, int, int)
    def processImages(self, count, processedImage, processedImagesList, isLast, time, number):
        """
        Processes selected images. Displays it onto a canvas.
        Technical: Creates img_model objects that encapsulate all of the useful data.
        """
        self.run_counter = number
        # Ordered Set
        if processedImage in self.imgList:
            self.imgList.remove(processedImage)
            self.imgList.add(processedImage)
        else:
            self.imgList.add(processedImage)
        self.send_data_to_report.emit(processedImagesList, self.dataList, self.imgList, self.u_cut, self.l_cut, self.rad_step,
                                      self.angle_inc)

        if self.is_started:
            # removes/deletes all canvases
            self.cleanCanvas()
        # fills canvas
        try:
            self.fillCanvas(self.imgList.__getitem__(self.current_index))
        except IndexError:
            self.current_index -= 1
            self.fillCanvas(self.imgList.__getitem__(self.current_index))
        if (not self.is_resized):
            self.applyResizing()
            self.is_resized = True
        # started
        self.is_started = True
        self.go_update.emit(self.current_index)
        #  Setting progress bar business
        self.progressBar.setValue(count)
        self.progressBar.valueChanged.emit(self.progressBar.value())
        self.current_index += 1
        self.runtime += time

    def applyResizing(self):
        """
        Makes so that screen can be resized after the images loaded.
        """
        self.resize(0.7 * self.screenDim.height(), 0.8 *self.screenDim.height())
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                           QtWidgets.QSizePolicy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.figureWidget.sizePolicy().hasHeightForWidth())
        self.figureWidget.setSizePolicy(sizePolicy)

    @pyqtSlot()
    def populateComboBox(self):
        """
        Populates combox box with the names.
        """
        self.selectImgBox.clear()
        for element in self.imgList:
            self.selectImgBox.addItem(element.filename.stem)
        self.selectImgBox.setCurrentIndex(self.current_index)

    def cleanCanvas(self):
        """
        Deletes the figure widget (i.e. cleans the canvas)
        """
        self.figureLayout.removeWidget(self.ang_dist_canvas)
        self.figureLayout.removeWidget(self.cart_dist_canvas)
        self.figureLayout.removeWidget(self.log_scl_canvas)
        self.figureLayout.removeWidget(self.img_canvas)
        self.ang_dist_canvas.deleteLater()
        self.cart_dist_canvas.deleteLater()
        self.img_canvas.deleteLater()
        self.log_scl_canvas.deleteLater()

    def fillCanvas(self, img):
        """
        Fills the canvas with the FFT-processed results based on the img.
        :param img: img to be processed
        """
        # updates canvases

        # upper-left tile
        self.img_canvas = QtWidgets.QLabel()
        self.img_canvas.setPixmap(QPixmap(self.saved_images_dir_name + "/orgImg_" + img.number.__str__() + ".png").scaled(300, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.img_canvas.setScaledContents(True)
        self.img_canvas.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)

        # upper-right tile
        self.log_scl_canvas = QtWidgets.QLabel()
        self.log_scl_canvas.setPixmap(QPixmap(self.saved_images_dir_name + "/logScl_" + img.number.__str__() + ".png").scaled(300, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.log_scl_canvas.setScaledContents(True)
        self.log_scl_canvas.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)

        # lower-left tile
        self.ang_dist_canvas = QtWidgets.QLabel()
        self.ang_dist_canvas.setPixmap(QPixmap(self.saved_images_dir_name + "/angDist_" + img.number.__str__() + ".png").scaled(300, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.ang_dist_canvas.setScaledContents(True)
        self.ang_dist_canvas.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)

        # lower-right tile
        self.cart_dist_canvas = QtWidgets.QLabel()
        self.cart_dist_canvas.setPixmap(QPixmap(self.saved_images_dir_name + "/cartDist_" + img.number.__str__() + ".png").scaled(300, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.cart_dist_canvas.setScaledContents(True)
        self.cart_dist_canvas.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)

        # adds them to layout
        self.figureLayout.addWidget(self.img_canvas, 0, 0)
        self.figureLayout.addWidget(self.log_scl_canvas, 0, 1)
        self.figureLayout.addWidget(self.ang_dist_canvas, 1, 0)
        self.figureLayout.addWidget(self.cart_dist_canvas, 1, 1)
        self.figureLayout.itemAtPosition(0, 1).widget().setToolTip("FFT Power Spectrum")
        self.figureLayout.itemAtPosition(0, 0).widget().setToolTip("Analyzed Image")
        self.figureLayout.itemAtPosition(1, 0).widget().setToolTip("Red Line = Fiber Orientation")
        self.figureLayout.itemAtPosition(1, 1).widget().setToolTip("Blue Line = Fiber Distribution")

    def processImagesFromComboBox(self, img):
        """
        Helps to process an image from using a Combo Box.
        :param img: image to be processed
        """
        if self.is_started:
            self.cleanCanvas()
        self.fillCanvas(img)

    def start(self):
        """
        Prepares applications to start.
        """
        # Processes selected images; sets up the labels and fills selectImgBox with references to images.
        self.kLabel.setText("k = ")
        self.muLabel.setText("μ =  ")
        self.RLabel.setText(('R' + u"\u00B2") + " = ")
        self.sigLabel.setText("σ = ")
        # clears canvas
        self.cleanCanvas()
        # clears combo-box
        self.selectImgBox.clear()
        # resets isStarted
        self.is_started = False
        # empties all images
        self.imgList.clear()
        # resets current index
        self.current_index = 0
        self.go_run.emit()
        self.removeTemp()

    @pyqtSlot(int)
    def setupLabels(self, num):
        """
        Sets up appropriate labels depending on which image is selected.
        :param num: index of the image currently displayed in the figure widget.
        """
        self.sigLabel.setText("σ = " + str(round(self.imgList.__getitem__(num).sig[0], 2)))
        self.kLabel.setText("k = " + str(round(self.imgList.__getitem__(num).k, 2)))
        self.muLabel.setText("μ = " + str(round(self.imgList.__getitem__(num).th, 2)))
        self.RLabel.setText(('R' + u"\u00B2") + " = " + str(round(self.imgList.__getitem__(num).R2, 2)))

    def nextImage(self):
        """
        Scrolls to next image.
        Uses a circular array as an underlying data structure. Main advantage is
        access by index; that is eliminate unnecessary search for item.
        """
        if (self.is_started):
            # updates current index
            self.current_index = (self.current_index + 1) % len(self.imgList)
            image = self.imgList.__getitem__(self.current_index)
            self.cleanCanvas()
            self.fillCanvas(image)
            self.setupLabels((self.current_index))
            self.selectImgBox.setCurrentIndex(self.current_index)

    def prevImage(self):
        """
        Scrolls to previous image.
        Uses a circular array as an underlying data structure. Main advantage is
        access by index; that is eliminate unnecessary search for item.
        """
        if (self.is_started):
            # updates current index
            self.current_index = (self.current_index - 1) % len(self.imgList)
            image = self.imgList.__getitem__(self.current_index)
            self.cleanCanvas()
            self.fillCanvas(image)
            self.setupLabels(self.current_index)
            self.selectImgBox.setCurrentIndex(self.current_index)

    @pyqtSlot(float, float, float, float)
    def updateValues(self, uCut, lCut, angleInc, radStep):
        """Updates settings per user's selection.
        :param uCut: upper cut
        :param lCut: lower cut
        :param angleInc: angle increment
        :param radStep: radial step
        :return: void
        """
        self.u_cut = uCut
        self.l_cut = lCut
        self.angle_inc = angleInc
        self.rad_step = radStep

    def connect_signals_to_slots(self):
        """Helper function to connect emitted signals to appropriate slots
        """
        self.send_data_to_report.connect(self.report_dialog.receiver)
        self.go_export.connect(self.report_dialog.do_test)
        self.go_run.connect(self.runner)
        self.go_update.connect(self.populateComboBox)
        self.go_update.connect(self.setupLabels)
        self.send_error.connect(self.handleError)
        self.go_process_images.connect(self.processImages)
        self.settingsBrowser.sendValues.connect(self.updateValues)

        self.exportButton.clicked.connect(self.export)
        self.startButton.clicked.connect(self.start)
        self.nextButton.clicked.connect(self.nextImage)
        self.prevButton.clicked.connect(self.prevImage)
        self.loadButton.clicked.connect(self.launch)
        self.clearButton.clicked.connect(self.clear)
        self.settingsButton.clicked.connect(self.settingsBrowser.do_change)
        self.selectImgBox.activated[str].connect(self.changeState)

    def changeState(self, filename):
        """Changes image according to user's selection via combo box.
        :param filename: name of which image to change state to
        :return: void
        """
        # find img
        for image in self.imgList:
            if image.filename.stem == filename:
                self.processImagesFromComboBox(image)
                self.sigLabel.setText("σ = " + str(round(image.sig[0], 2)))
                self.kLabel.setText("k = " + str(round(image.k, 2)))
                self.muLabel.setText("μ = " + str(round(image.th, 2)))
                self.RLabel.setText(('R' + u"\u00B2") + " = " + str(round(image.R2, 2)))
                # sets current index to the index of the found image.
                self.current_index = self.imgList.index(image)

    def create_temp_dir(self):
        """Creates a directory to where app would dump all the processed images for canvases.
        Note, 10,000,000 is a hardcoded value (I realize it), but for intended purposes, it
        is okay. The goal was to make sure that the user doesn't have this directory already created in system.
        :return: void
        """
        directory = "temp"
        isCreated = False
        while not isCreated:
            randomNum = random.randint(0, 100000000) # 10,000,000
            self.saved_images_dir_name = directory + randomNum.__str__()
            if not os.path.exists(directory):
                os.makedirs(self.saved_images_dir_name)
                isCreated = True

    def receiveDim(self):
        """Calculates dimensions of the screen.
        :return: dimension of a screen and DPI
        """
        screenDim = QDesktopWidget().availableGeometry()
        screen = QtWidgets.QApplication.primaryScreen()
        dpi = screen.logicalDotsPerInch()
        return screenDim, dpi

    def closeEvent(self, event):
        """
        Makes sure to delete the temprorary directory with all the secondary images
        :param event:
        :return: none
        """
        self.delete_dir(self.saved_images_dir_name)

    def delete_dir(self, dir):
        """
        Deletes a given directory. In context of application, it's used when
        :param dir:
        :return:
        """
        import shutil
        try:
            shutil.rmtree(dir)
        except:
            pass
            # means directory has not been created. if usre opens an app and then immediately closes it.


class myThread(threading.Thread):
    """
    Class responsible for heavy lifting of computerVision algorithm
    """
    def __init__(self, sig, errorSig, bar, dir, num):
        """
        Initialises attributes used to process the image via computerVision and send it back to the running application.
        :param sig: signal indicating that UI should be updated
        :param errorSig: send_error signal from the fft_mainWindow
        :param bar: the progress bar
        :param dir: full path to directory where to put the secondary images in
        :param num: number indicating the order of image being processed (useful in naming the secondary image files.)
        :return: none
        """
        super(myThread, self).__init__()
        self.uCut = 0
        self.lCut = 0
        self.angleInc = 0
        self.radStep = 0
        self.screenDim = 0
        self.dpi = 0
        self.sig = sig
        self.filenames = []
        self.bar = bar
        self.errorSig = errorSig
        self.directory = dir
        self.number = num

    def update_values(self,uCut,lCut,angleInc,radStep,screenDim,dpi,filenames):
        """
        Updated the values that are modified during the run time (i.e. settings)
        :param uCut: upper cut
        :param lCut: lower cut
        :param angleInc: angle increment
        :param radStep: radial step
        :param screenDim: dimensions of a screen
        :param dpi: DPI of a primary screem
        :param filenames: list of names of files to be processed
        :return: none
        """
        self.lCut = lCut
        self.uCut = uCut
        self.angleInc = angleInc
        self.radStep = radStep
        self.screenDim = screenDim
        self.dpi = dpi
        self.filenames = filenames

    def run(self):
        """
        Processes the images inside of filenames and sends the result of each image back to the fft_mainWindow.
        :return: none
        """
        processedImagesList = []
        count = 0
        toContinue = True
        isZeroException = 0
        isLast = 0
        for filename in self.filenames:
            toContinue = True
            # Retrieve Figures from data analysis code
            try:
                sig, k, th, R2, angDist,  cartDist, logScl,  orgImg,  figWidth, figHeigth, runtime = computerVision_BP.process_image(filename,
                                                                                               self.uCut,
                                                                                               self.lCut, self.angleInc,
                                                                                               self.radStep, self.screenDim,
                                                                                               self.dpi,
                                                                                               self.directory,
                                                                                               self.number)

                # Starting from Python3, there is a distinctin between bytes and str. Thus, I can't use
                # methods of str on bytes. However I need to do that in order to properly encode the image
                # into b64. The main thing is that bytes-way produces some improper characters that mess up
                # the decoding process. Hence, decode(utf-8) translates bytes into str.

                angDistEncoded = base64.encodebytes(open(self.directory + "/" + 'angDist_' + self.number.__str__() + '.png', 'rb').read()).decode('utf-8')
                cartDistEncoded = base64.encodebytes(open(self.directory + "/" + 'cartDist_' + self.number.__str__() + '.png', 'rb').read()).decode('utf-8')
                logSclEncoded = base64.encodebytes(open(self.directory + "/" + 'logScl_' + self.number.__str__() + '.png', 'rb').read()).decode('utf-8')
                orgImgEncoded = base64.encodebytes(open(self.directory + "/" +  'orgImg_' + self.number.__str__() + '.png', 'rb').read()).decode('utf-8')

                processedImage = img_model.ImgModel(
                    filename=filename,
                    sig = sig,
                    k=k,
                    th=th,
                    R2=R2,
                    orgImg=orgImg,
                    orgImgEncoded=orgImgEncoded,
                    logScl=logScl,
                    logSclEncoded=logSclEncoded,
                    angDist=angDist,
                    angDistEncoded=angDistEncoded,
                    cartDist=cartDist,
                    cartDistEncoded=cartDistEncoded,
                    timeStamp=datetime.datetime.now().strftime("%A, %d. %B %Y %I:%M%p"),
                    number=self.number)
                self.number += 1
                processedImagesList.append(processedImage)
                count += 1
                if count == len(self.filenames):
                    isLast = 1
            except TypeError:
                toContinue = False
            except ValueError:
                toContinue = False
            except OSError:
                toContinue = False
            except ZeroDivisionError:
                toContinue = False
                isZeroException = 1
            finally:
                if (toContinue):
                    self.sig.emit(count, processedImage, processedImagesList, isLast, runtime, self.number)
                else:
                    self.errorSig.emit(self.filenames, count, isZeroException)
        # hides the bar after processing all the images
        if toContinue:
            time.sleep(0.5)
            self.bar.setWindowOpacity(0)
            self.bar.hide()


def main():
    """
    Enters an event-loop.
    """
    app = QtWidgets.QApplication(sys.argv)
    fft_app = fft_mainWindow()
    fft_app.receiveDim()
    fft_app.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
