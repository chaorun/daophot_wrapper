#!/usr/bin/env python

import os, sys
import subprocess
import select
import time
import shutil

sys.path.append("/work/podi_prep56")
from podi_definitions import *

from optparse import OptionParser


class ProcessHandler( object ):

    def __init__(self, args, read_timeout=0.1, verbose=True, send_delay=0.0):

        self.proc = subprocess.Popen(
            args,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.stdout_poll = select.poll()
        self.stdout_poll.register(self.proc.stdout, select.POLLIN)

        self.read_timeout = read_timeout
        self.verbose = verbose
        self.send_delay = send_delay

    def read(self, timeout=None):

        retcode = self.proc.poll()
        if (not retcode == None):
            raise Error("Process dead!")
            
        if (timeout == None): timeout=self.read_timeout

        output = []
        start_time = time.time()
        while ((time.time() - start_time) < timeout):
            poll_result = self.stdout_poll.poll(0)

            if (poll_result):
                filedesc, mask = poll_result[0]
                if (mask & select.POLLIN):
                    line = self.proc.stdout.read(1)
                    output.append(line)
            else:
                time.sleep(0.001)

        if (self.verbose):
            sys.stdout.write("".join(output))
        return "".join(output)

    def read_until(self, until_text, timeout=1):
        if (type(until_text) == str):
            until_text = [until_text]
        start_time = time.time()
        full_return = ""
        found = -1
        while(((time.time() - start_time) < timeout or timeout<0) and found<0):
            new_text = self.read()
            full_return += new_text
            for match_id, ut in enumerate(until_text):
                #print ut, "\n", full_return
                if (full_return.find(ut) > 0):
                    found = match_id
                    break
        return full_return, found

    def write(self, text, retry=3):
        retries = 0
        while(retries < retry):
            try:
                self.proc.stdin.write(text)
                break
            except IOError:
                retries += 1
                time.sleep(0.05)
                continue
            except:
                pass
                #print e
        if (self.verbose):
            sys.stdout.write(text)
        time.sleep(self.send_delay)
        return

    def write_and_read(self, text):
        self.write(text)
        return self.read()



class DAOPHOT ( object ):

    def __init__(self, options, fitsfile, threshold):

        self.cmd_options = options
        self.detection_threshold = threshold
        self.fitsfile = fitsfile

        self.daophot_exe = "%s/daophot" % (self.cmd_options.dao_dir)
        self.allstar_exe = "%s/allstar" % (self.cmd_options.dao_dir)
        

        #
        # open FITS file and read some important parameters
        #
        self.hdulist =  pyfits.open(filename)

        self.gain = self.hdulist[0].header['GAIN'] if 'GAIN' in self.hdulist[0].header \
                    else 1.5
        self.readnoise = self.hdulist[0].header['RDNOISE'] if 'RDNOISE' in self.hdulist[0].header \
                         else 6.5

        self.files = {}

        self.running = False
        if (not self.running):
            self.start_daophot()


    def start_daophot(self):
        #
        # Start up DAOPhot
        #
        self.daophot = ProcessHandler([self.daophot_exe], verbose=True)

        self.daophot.read()
        # first question in READNOISE
        # Value unacceptable --- please re-enter
        #
        #                        READ NOISE (ADU; 1 frame) = 1.4
        #
        self.daophot.write("%.2f\n" % (self.readnoise))


        self.daophot.read()
        # Value unacceptable --- please re-enter
        #
        #                        GAIN (e-/ADU; 1 frame) = 1.4
        #
        self.daophot.write("%.2f\n" % (self.gain))
        self.daophot.read()

        #
        # Now we are ready for action
        #
        
    def get_file(self, extension):
        return "%s.%s" % (self.fitsfile[:-5], extension)

    def get_process_handler(self):
        return self.daophot


    def wait_for_prompt(self):
        self.daophot.read_until("Command:")


    def attach(self, filename=None):
        
        if (not filename == None):
            self.fitsfile = filename

        self.daophot.write("ATTACH %s\n" % (self.fitsfile))
#        self.daophot.read_until("Input image name:")

#        self.daophot.write("%s\n" % (self.fitsfile))
        self.wait_for_prompt()


    def options(self, **kwargs):

        if (kwargs == None):
            return

        self.daophot.write("OPTION\n")
        self.daophot.read_until("File with parameters (default KEYBOARD INPUT):")

        self.daophot.write("\n")
        self.daophot.read_until("OPT>")

        for key, value in kwargs.iteritems():

            # set options
            self.daophot.write("%s = %.2f\n" % (key, value))
                # readnoise=None,
                # gain=None,
                # fwhm=None,
                # watch=None,
                # psf_radius=None,

            # and wait for new prompt
            self.daophot.read_until("OPT>")

        # empty string takes us back to command prompt
        self.daophot.write("\n")
        self.wait_for_prompt()

    def sky(self):
        self.daophot.write("SKY\n")
        self.wait_for_prompt()


    def find(self, avg=1, sum=1, coo_file=None):

        self.daophot.write("FIND\n")
        #      Sky mode and standard deviation =   -0.036   28.680
        #
        #              Clipped mean and median =    4.045    2.679
        #   Number of pixels used (after clip) = 15,088
        #                       Relative error = 1.14
        #
        #                 Number of frames averaged, summed:    
        self.daophot.read_until("Number of frames averaged, summed:")

        self.daophot.write("%d,%d\n" % (avg, sum))
        #         File for positions (default leo1_nans.coo):

        
        self.daophot.read_until("File for positions")
        if (not coo_file == None):
            # XXXXX
            self.files['coo'] = coo_file
        else:
            self.files['coo'] = self.get_file('coo')

        #coo_file = tmpfile[:-5]+".coo"
        clobberfile(self.files['coo'])
        self.daophot.write("%s\n" % (self.files['coo']))

        #
        # ...
        #
        #                           Are you happy with this? yes
        #
        catdump, found = self.daophot.read_until(["Are you happy with this?"], timeout=-1)
        self.daophot.write("yes\n")

        self.wait_for_prompt()

    def phot(self, ap_file=None, coo_file=None, **kwargs):

        self.daophot.write("PHOT\n")
        #
        #      File with aperture radii (default photo.opt):
        self.daophot.read_until("File with aperture radii (default photo.opt):")


        self.daophot.write("\n")
        #    
        # Error opening input file photo.opt                                              
        #
        #
        #  A1  RADIUS OF APERTURE  1 =     0.00     A2  RADIUS OF APERTURE  2 =     0.00
        #  A3  RADIUS OF APERTURE  3 =     0.00     A4  RADIUS OF APERTURE  4 =     0.00
        #  A5  RADIUS OF APERTURE  5 =     0.00     A6  RADIUS OF APERTURE  6 =     0.00
        #  A7  RADIUS OF APERTURE  7 =     0.00     A8  RADIUS OF APERTURE  8 =     0.00
        #  A9  RADIUS OF APERTURE  9 =     0.00     AA  RADIUS OF APERTURE 10 =     0.00
        #  AB  RADIUS OF APERTURE 11 =     0.00     AC  RADIUS OF APERTURE 12 =     0.00
        #  IS       INNER SKY RADIUS =     0.00     OS       OUTER SKY RADIUS =     0.00
        #
        # PHO> 
        self.daophot.read_until("PHO>")

        #
        # Now parse all options requested by the user
        #
        for key, value in kwargs.iteritems():

            # set options
            self.daophot.write("%s = %.2f\n" % (key, value))

            # and wait for new prompt
            self.daophot.read_until("PHO>")

        #
        # empty string takes us back to command prompt
        #
        self.daophot.write("\n")


        #
        #  A1  RADIUS OF APERTURE  1 =     7.00     A2  RADIUS OF APERTURE  2 =     0.00
        #  A3  RADIUS OF APERTURE  3 =     0.00     A4  RADIUS OF APERTURE  4 =     0.00
        #  A5  RADIUS OF APERTURE  5 =     0.00     A6  RADIUS OF APERTURE  6 =     0.00
        #  A7  RADIUS OF APERTURE  7 =     0.00     A8  RADIUS OF APERTURE  8 =     0.00
        #  A9  RADIUS OF APERTURE  9 =     0.00     AA  RADIUS OF APERTURE 10 =     0.00
        #  AB  RADIUS OF APERTURE 11 =     0.00     AC  RADIUS OF APERTURE 12 =     0.00
        #  IS       INNER SKY RADIUS =    10.00     OS       OUTER SKY RADIUS =    20.00
        #
        #       Input position file (default leo1_nans.coo):
        self.daophot.read_until("Input position file")

        _coo = self.files['coo'] if coo_file == None else coo_file
        self.daophot.write("%s\n" % (_coo))
        #                Output file (default leo1_nans.ap):

        self.daophot.read_until("Output file")
        
        if (not ap_file == None):
            self.files['ap'] = ap_file
        elif 'ap' not in self.files:
            self.files['ap'] = self.get_file("ap")
        clobberfile(self.files['ap'])
        self.daophot.write("%s\n" % (self.files['ap']))

        self.wait_for_prompt()
        

        # daophot.write_and_read("%s\n" % (coo_file))

        # ap_file = tmpfile[:-5]+".ap"
        # clobberfile(ap_file)
        # daophot.write("%s\n" % (ap_file))
        # #
        # # ... lots of photometry coming now ...
        # #
        # phot, found = daophot.read_until(["Command:"], timeout=-1)


    def pick(self, nstars=15, maglimit=14, lst_file=None, ap_file=None):

        #
        # Now do some PSF modeling
        #
        self.daophot.write("PICK\n")
        #
        #            Input file name (default leo1_nans.ap):
        self.daophot.read_until("Input file name")

        _ap = self.files['ap'] if (ap_file == None) else ap_file
        self.daophot.write("%s\n" % (_ap))
        #       Desired number of stars, faintest magnitude: 

        self.daophot.read_until("Desired number of stars, faintest magnitude:")
        self.daophot.write("%d,%d\n" % (nstars, maglimit))

        #           Output file name (default leo1_nans.lst):
        self.daophot.read_until("Output file name")

        if (not lst_file == None):
            self.files['lst'] = lst_file
        elif (not 'lst' in self.files):
            self.files['lst'] = self.get_file('lst')
        clobberfile(self.files['lst'])

        self.daophot.write("%s\n" % (self.files['lst']))

        self.wait_for_prompt()

        #retstr, found = daophot.read_until(["candidates were found."], timeout=-1)
        #retstr, found = daophot.read_until(["Command:"], timeout=-1)
        #
        #        15 suitable candidates were found.
        #



    def psf(self, interactive=False, ap_file=None, lst_file=None, psf_file=None):

        
        self.daophot.write("PSF\n")
        #  File with aperture results (default leo1_nans.ap):
        self.daophot.read_until("File with aperture results")

        _ap = self.files['ap'] if (ap_file == None) else ap_file
        self.daophot.write("%s\n" % (_ap))

        self.daophot.read_until("File with PSF stars")
        #        File with PSF stars (default leo1_nans.lst): 

        _lst = self.files['lst'] if (lst_file == None) else lst_file
        self.daophot.write("%s\n" % (_lst))

        #           File for the PSF (default leo1_nans.psf):
        self.daophot.read_until("File for the PSF")
        
        if (not psf_file == None):
            self.files['psf'] = psf_file
        elif (not 'psf' in self.files):
            self.files['psf'] = self.get_file('psf')
        clobberfile(self.files['psf'])
        
        self.daophot.write("%s\n" % (self.files['psf']))

        done = False
        valid_psf_model = True
        while (not done):
            retstr, found = self.daophot.read_until(["Use this one?",
                                                     "Try this one anyway?",
                                                     "Failed to converge",
                                                     "File with PSF stars and neighbors"])

            if (found < 0):
                continue
            elif (found == 0):
                #  Use this one? y

                if (interactive):
                    user_input = raw_input("???")
                    if (user_input == ""):
                        user_done = True

                    self.daophot.write("%s\n" % (user_input))
                else:
                    self.daophot.write("yes\n")

            elif (found == 1):
                #  Use this one? y

                if (interactive):
                    user_input = raw_input("???")
                    if (user_input == ""):
                        user_done = True

                    self.daophot.write("%s\n" % (user_input))
                else:
                    self.daophot.write("no\n")

            elif (found == 2):
                # Failed to converge.
                valid_psf_model = False
                done = True

            elif (found == 3):
                done = True
                valid_psf_model = True


        return valid_psf_model

        # user_done = False
        # candidates_checked = 0
        # while (not user_done and candidates_checked < n_psf_candidates):
        #     text = daophot.read()
        #     print text

        #     user_input = raw_input("???")
        #     if (user_input == ""):
        #         user_done = True

        #     candidates_checked += 1

        # # for psf_candidate in range(n_psf_candidates):
        # #     psf = daophot.read_until("Use this one?")
        # #     daophot.write("yes\n")


        # ret, found = daophot.read_until(['Failed to converge.',
        #                                  'Command',
        #                                  '>>'])

        # valid_psf_model = True
        # if (found and ret.find("Failed to converge")):
        #     print "XXXXX\n"*10
        #     valid_psf_model = False



    def exit(self):
        self.daophot.write("EXIT\n")
        self.running = False

    def save_files(self, out_directory):
        if (not os.path.isdir(out_directory)):
            os.mkdir(out_directory)

        # Now move all files used during execution to the 
        # specified output directory
        for ftype in self.files:
            fn = self.files[ftype]
            _, bn = os.path.split(fn)
            try:
                shutil.copyfile(fn, "%s/%s" % (out_directory, bn))
            except:
                pass



class ALLSTAR ( object ):


    def __init__(self, options, fitsfile, 
                 psf_file=None,
                 ap_file=None, 
                 als_file=None, 
                 starsub_file=None,
                 **kwargs):

        print "This all ALLSTAR"

        self.cmd_options = options
        self.fitsfile = fitsfile

        self.allstar_exe = "%s/allstar" % (self.cmd_options.dao_dir)

        self.files = {}
        self.files['psf'] = self.get_file('psf') if psf_file == None else psf_file
        self.files['ap'] = self.get_file('ap') if ap_file == None else ap_file
        self.files['als'] = self.get_file('als') if als_file == None else als_file
        self.files['starsub'] = self.get_file('starsub.fits') if starsub_file == None else starsub_file

        print kwargs

        self.running = False
        if (not self.running):
            self.start_allstar(kwargs)

    def get_file(self, extension):
        return "%s.%s" % (self.fitsfile[:-5], extension)


    def start_allstar(self, kwargs):

        self.allstar = ProcessHandler([self.allstar_exe], verbose=True)
        self.allstar.read_until("OPT>")

        for key, value in kwargs.iteritems():
            self.allstar.write("%s = %.2f\n" % (key, value))
            self.allstar.read_until("OPT>")

        self.allstar.write("\n")

        self.allstar.read_until("Input image name:")
        self.allstar.write("%s\n" % (self.fitsfile))

        self.allstar.read_until("File with the PSF")
        self.allstar.write("%s\n" % (self.files['psf']))

        self.allstar.read_until("Input file")
        self.allstar.write("%s\n" % (self.files['ap']))

        self.allstar.read_until("File for results")
        clobberfile(self.files['als'])
        self.allstar.write("%s\n" % (self.files['als']))

        self.allstar.read_until("Name for subtracted image")
        clobberfile(self.files['starsub'])
        self.allstar.write("%s\n" % (self.files['starsub']))

        self.allstar.read_until(["Finished", "Good bye"], timeout=-1)

    def save_files(self, out_directory):
        if (not os.path.isdir(out_directory)):
            os.mkdir(out_directory)
        # Now move all files used during execution to the 
        # specified output directory
        for ftype in self.files:
            fn = self.files[ftype]
            _, bn = os.path.split(fn)
            try:
                shutil.copyfile(fn, "%s/%s" % (out_directory, bn))
            except:
                pass


if __name__ == "__main__":

    parser = OptionParser()
    parser.add_option("", "--dao", dest="dao_dir",
                      help="Path holding DAOphot executables",
                      default="/home/rkotulla/install/daophot")
    parser.add_option("-t", "--threshold", dest="threshold",
                      help="Detection Threshold",
                      default=10,
                      type=float)
    parser.add_option("-a", "--allstar", dest="allstar",
                      help="ALLSTAR only mode",
                      default="",
                      type=str)
    parser.add_option("-o", "--outdir", dest="outdir",
                      help="Directory for output files",
                      default=".",
                      type=str)
    (options, cmdline_args) = parser.parse_args()

    print options
    print type(options.threshold)
    # sys.exit(0)

    daophot_exe = "%s/daophot" % (options.dao_dir)
    allstar_exe = "%s/allstar" % (options.dao_dir)

    if (options.allstar == ""):
        filename = cmdline_args[0]
        print("Running DAOPhot on %s" % (filename))

        # open file and read some parameters
        hdulist = pyfits.open(filename)

        gain = 1.3 #hdulist[0].header['GAIN']
        readnoise = 7.0 #hdulist[0].header['RDNOISE']


        weightfile = filename[:-5]+".weight.fits"
        if (os.path.isfile(weightfile)):
            weights_hdu = pyfits.open(weightfile)
            weights = weights_hdu[0].data

            hdulist[0].data[weights <= 0] = numpy.NaN

        # write the hdulist as a temp-file
        tmpfile = "/tmp/pid%d.fits" % (os.getpid())
        hdulist.writeto(tmpfile, clobber=True)   
        print "tmp-file:", tmpfile

        #time.sleep(2)

        dao = DAOPHOT(options=options, 
                      fitsfile=tmpfile, 
                      threshold=options.threshold)

        dao.attach(tmpfile)


        psf_width = 35.0
        fitting_radius = 3 #10. #10*psf_width
        dao.options(thresh=options.threshold,
                    psf=psf_width,
                    fitting=fitting_radius,
                    extra=5,
                    watch=0)


        dao.sky()

        dao.find(avg=2)

        dao.phot(IS=10, OS=20, A1=4.5, A2=5)

        dao.pick(nstars=25, maglimit=14)

        good_psf = dao.psf(interactive=False)

        dao.exit()
        
        dao.save_files(options.outdir)
    else:
        tmpfile = options.allstar

    if (good_psf):
        # allstar = ALLSTAR(options, tmpfile, FIT=fitting_radius, IS=0, OS=4)
        allstar = ALLSTAR(options, tmpfile, FIT=fitting_radius, IS=4, OS=40)
        allstar.save_files(options.outdir)
    else:
        print "Can't run ALLSTAR since we did not derive a converged PSF fit"

    sys.exit(0)

        
    # Shutdown daophot
    daophot.write("EXIT\n")
    daophot.read()


    if (not valid_psf_model):
        sys.exit(0)

