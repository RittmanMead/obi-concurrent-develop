import os
import re
import sys
import tempfile
import platform
from glob import glob
from shutil import copyfile, rmtree
from argparse import ArgumentParser
from ConfigParser import SafeConfigParser
from subprocess import Popen, PIPE, STDOUT, call

SCRIPT_DIR = os.path.abspath(os.path.dirname(sys.argv[0]))
CURRENT_DIR = os.getcwd()

try:
	os.chdir(SCRIPT_DIR)  # Change to script directory

	# ArgumentParser to parse arguments and options
	arg_parser = ArgumentParser(description="Rittman Mead RPD SVN Merge Script \n(MP/RM Sep 2015)")
	arg_parser.add_argument('-r', '--original', help="Full path of the Original RPD.")
	arg_parser.add_argument('-u', '--current', help="Full path of the Current RPD.")
	arg_parser.add_argument('-m', '--modified', help="Full path of the Modified RPD.")
	arg_parser.add_argument('-p', '--password', help="Password of all the RPDs. Assumed to be the same for this tool.")
	arg_parser.add_argument('-c', '--config', default='config.ini', help='Config file to be used. Default: "config.ini"')
	arg_parser.add_argument('-o', '--output', default='output.rpd',
						help='Path to save as the output. Default: "output.rpd". Cannot be the same as any of the input files.')
	arg_parser.add_argument('-a', '--autoOpen', action="store_true", default=False,
						help='Automatically opens new RPD after merge.')
	arg_parser.add_argument('-d', '--deploy', action="store_true", default=False,
						help='Deploys the RPD and restarts the BI Server.')
	arg_parser.add_argument('-v', '--verbose', action='count', default=False,
						help='Enables debug output')
	arg_parser.add_argument('-t', '--tidyup', action="store_true", default=False,
						help='If set then all intermediate files will be deleted. ')
	arg_parser.add_argument('--reverse', action='store_true', default=False,
						help='Reverse the current/modified merge candidates when doing a three-way merge.')
	arg_parser.add_argument('--source_url', help='SVN URL for the branch to be merged FROM')
	arg_parser.add_argument('--target_url', help='SVN URL for the branch to merge changes INTO.')
	arg_parser.add_argument('--featureName', help='Feature name. Should usually be a JIRA ticket id')
	arg_parser.add_argument('--hotfixName', help='Hotfix name. Should usually be a JIRA ticket id')
	arg_parser.add_argument('--releaseName', help='Release name. Usually an incrementing version number')
	arg_parser.add_argument('--commitMessage', help='SVN Commit message')
	arg_parser.add_argument('--action', choices=['startFeature', 'startRelease', 'startReleaseHotfix', 'startHotfix',
											'finishFeature', 'finishRelease', 'finishReleaseHotfix', 'finishHotfix',
											'refreshFeature', 'standaloneRPDMerge', 'reintegrate'])
	args = arg_parser.parse_args()

	# Parse config parameters
	config_file = args.config
	if not os.path.exists(config_file):
		print '\n**Config file %s not found. Exiting.' % config_file
		sys.exit(1)

	conf_parser = SafeConfigParser()
	conf_parser.read(config_file)

	OBIEE_VERSION = conf_parser.get('OBIEE', 'OBIEE_VERSION')
	CLIENT_ONLY = conf_parser.getboolean('OBIEE', 'CLIENT_ONLY')
	OBIEE_HOME = os.path.abspath(conf_parser.get('OBIEE', 'OBIEE_HOME'))

	# Optional path setting for clients and server and mixed installations
	OBIEE_CLIENT = os.path.abspath(conf_parser.get('OBIEE', 'OBIEE_CLIENT'))
	if CLIENT_ONLY is False and OBIEE_CLIENT == '':
		OBIEE_CLIENT = os.path.join(OBIEE_HOME, 'user_projects', 'domains')
	elif CLIENT_ONLY is True and OBIEE_CLIENT == '':
		OBIEE_CLIENT = OBIEE_HOME
	else:
		OBIEE_CLIENT = os.path.abspath(conf_parser.get('OBIEE', 'OBIEE_CLIENT'))

	RPD_PW = conf_parser.get('OBIEE', 'RPD_PW')

	SVN_BIN = conf_parser.get('SVN', 'SVN_BIN')
	SVN_BASE_URL = conf_parser.get('SVN', 'SVN_BASE_URL')
	SVN_TRUNK = conf_parser.get('SVN', 'SVN_TRUNK')
	SVN_DEVELOP = conf_parser.get('SVN', 'SVN_DEVELOP')
	SVN_DEV_BRANCH_ROOT = conf_parser.get('SVN', 'SVN_DEV_BRANCH_ROOT')
	SVN_RELEASE_BRANCH_ROOT = conf_parser.get('SVN', 'SVN_RELEASE_BRANCH_ROOT')
	SVN_RELEASE_HF_BRANCH_ROOT = conf_parser.get('SVN', 'SVN_RELEASE_HF_BRANCH_ROOT')
	SVN_HF_BRANCH_ROOT = conf_parser.get('SVN', 'SVN_HF_BRANCH_ROOT')

	# Initiliases bi-init and runcat command variables
	if platform.system() == 'Linux':
		# This won't work for multi-instance BI Homes (instance2 etc)
		BIINIT_PATH = '%s/instances/instance1/bifoundation/OracleBIApplication/coreapplication/setup/bi-init.sh' % OBIEE_HOME

	else:
		if CLIENT_ONLY:
			BIINIT_PATH = '%s\\oraclebi\\orahome\\bifoundation\\server\\bin\\bi_init.bat' % OBIEE_HOME
		else:
			# This won't work for multi-instance BI Homes (instance2 etc)
			BIINIT_PATH = '%s\\instances\\instance1\\bifoundation\\OracleBIApplication\\coreapplication\\setup\\bi-init.cmd' \
						  % OBIEE_HOME
		BIINIT_PATH = BIINIT_PATH.replace(' ', '^ ')

	ORIG_RPD = args.original
	CURR_RPD = args.current
	MODI_RPD = args.modified
	OUT_RPD = args.output
	ACTION = args.action
	FEATURE_NAME = args.featureName
	RELEASE_NAME = args.releaseName
	HOTFIX_NAME = args.hotfixName
	RPD_PASS = args.password
	if RPD_PASS is None:
		RPD_PASS = RPD_PW
	AUTO_OPEN = args.autoOpen
	DEPLOY = args.deploy
	TIDY = args.tidyup
	COMMIT_MESSAGE = args.commitMessage
	SOURCE_URL = args.source_url
	TARGET_URL = args.target_url
	REVERSE_MERGE_CANDIDATES = args.reverse

	# Arg validation
	if ORIG_RPD is not None and CURR_RPD is not None and MODI_RPD is not None and OUT_RPD is not None:
		ORIG_RPD = os.path.join(CURRENT_DIR, args.original)
		CURR_RPD = os.path.join(CURRENT_DIR, args.current)
		MODI_RPD = os.path.join(CURRENT_DIR, args.modified)
		OUT_RPD = os.path.join(CURRENT_DIR, args.output)
		ACTION = 'standaloneRPDMerge'

	if ACTION == 'reintegrate' and (SOURCE_URL is None or TARGET_URL is None or RPD_PASS is None or COMMIT_MESSAGE is None):
		arg_parser.print_help()
		print '\n**PROBLEM: If reintegrate is specified then the source and target SVN URLs must be given, along with ' \
			  'the RPD password and a commit message\n\nExiting.'
		sys.exit(1)

	if RPD_PASS is None and not (ACTION == 'startFeature' or ACTION == 'startRelease' or ACTION == 'startHotfix'
								 or ACTION == 'startReleaseHotfix'):
		arg_parser.print_help()
		print '\n**PROBLEM: RPD password (--password) must be specified for any operation that MAY need to do a three ' \
			  'way merge (even if it ends up not doing). \n\n\n\nExiting.'
		sys.exit(1)

	if (ACTION == 'startFeature' or ACTION == 'finishFeature' or ACTION == 'refreshFeature') and FEATURE_NAME is None:
		arg_parser.print_help()
		print '\n**PROBLEM: FeatureName (--featureName) must be specified.\n\n\n\nExiting.'
		sys.exit(1)

	if (ACTION == 'startRelease' or ACTION == 'finishRelease' or ACTION == 'startReleaseHotfix'
		or ACTION == 'finishReleaseHotfix' ) and RELEASE_NAME is None:
		arg_parser.print_help()
		print '\n**PROBLEM: ReleaseName (--releaseName) must be specified.\n\n\n\nExiting.'
		sys.exit(1)

	if (ACTION == 'startHotfix' or ACTION == 'finishHotfix' or ACTION == 'startReleaseHotfix'
		or ACTION == 'finishReleaseHotfix') and HOTFIX_NAME is None:
		arg_parser.print_help()
		print '\n**PROBLEM: HotfixName (--hotfixName) must be specified.\n\n\n\nExiting.'
		sys.exit(1)

	if not ACTION == 'standaloneRPDMerge':
		if not os.path.exists(SVN_BIN):
			print '\n**SVN binary not found at %s. \n\tPlease update config.ini. \n\tAborting.' % SVN_BIN
			sys.exit(1)

	# Misc vars
	PATCH_FILE = tempfile.NamedTemporaryFile(suffix='.patch.xml', delete=False).name
	COMPARE_LOG = os.path.join(CURRENT_DIR, 'compareRPD.log')
	PATCH_LOG = os.path.join(CURRENT_DIR, 'patchRPD.log')

except Exception, err:
	print '\n\nException caught:\n\n%s ' % err
	print '\n\n\tFailed to get command line arguments. Exiting.'
	sys.exit(1)


def delete_folders(folder_array):
	"""Delete folder tree."""
	for folder in folder_array:
		if os.path.exists(folder):
			try:
				rmtree(folder)
			except Exception, error:
				print '\n\nException caught:\n\n%s ' % error
				print '\nError: Failed to delete folder %s' % folder
				return False
	return True


def svn_checkout(url, wc, force=False):
	"""Checks out SVN repository from an SVN URL to a specific director."""

	if os.path.exists(wc):
		if not force:
			return False
		else:
			try:
				delete_folders([wc])
			except Exception, error:
				print 'Failed to remove Working Copy %s\n%s' % (wc, error)
				return False

	script = [SVN_BIN, 'checkout', url, wc]

	try:
		p = Popen(script, stdout=PIPE, stderr=STDOUT)
		p.wait()
		data = p.communicate()
		if 'Checked out revision' in data[0]:
			return True
		else:
			return False
	except Exception, error:
		print '\n**Error during checkout. \n\tScript: %s\n\tError: %s ' % (script, error)
		return False


def svn_copy(srcurl, dsturl, commit_message=None):
	if commit_message is None:
		commit_message = 'Branch from %s' % srcurl

	script = [SVN_BIN, 'copy', srcurl, dsturl, '-m', commit_message]

	tmpwc = tempfile.mkdtemp(prefix='rm_rpdco')
	if svn_checkout(dsturl, tmpwc, True):
		print '\n**Destination already exists in SVN repository!'
		print '\n\tError encountered when trying to do svn copy %s %s' % (srcurl, dsturl)
		return False

	try:
		p = Popen(script, stdout=PIPE, stderr=STDOUT)
		p.wait()
		data = p.communicate()
		if 'Committed revision' in data[0]:
			print data[0]
			return True
		else:
			print '\n** Failed to copy.\n\t%s' % data[0]
			return False
	except Exception, error:
		print '\n**Error during copy. \n\tScript: %s\n\tError: %s ' % (script, error)
		return False


def svn_merge(srcurl, target_wc, accept='postpone', re_integrate=True):
	if not os.path.exists(target_wc):
		print '\n**Target Working Copy (%s) does not exist. Aborting merge.' % target_wc
		return False

	if re_integrate:
		reintegrate_arg = '--reintegrate'
	else:
		reintegrate_arg = ''

	script = [SVN_BIN, 'merge', reintegrate_arg, '--accept', accept, srcurl, target_wc]

	try:
		p = Popen(script, stdout=PIPE, stderr=STDOUT)
		p.wait()
		data = p.communicate()
		if 'Recording mergeinfo for merge' in data[0]:
			return data[0]
		elif data[0] == '':
			return True
		else:
			print '\n** Failed to merge (01)).\n----\n%s\n----\n' % '\n'.join(str(v) for v in data)
			return False
	except Exception, error:
		print '\n**Error during merge. \n\tScript: %s\n\tError: %s ' % (script, error)
		return False


def svn_commit(wc, commit_message):
	if not os.path.exists(wc):
		print '\n**Working Copy (%s) does not exist. Aborting commit.' % wc
		return False

	script = [SVN_BIN, 'commit', '-m', commit_message, wc]

	try:
		p = Popen(script, stdout=PIPE, stderr=STDOUT)
		p.wait()
		data = p.communicate()
		regex_pattern = '.*(Committed revision [0-9]*)\..*'
		match = re.findall(regex_pattern, data[0])

		if match:
			print 'Commit successful!  -->   %s' % match[0]
			return True
		else:
			print '\n** Failed to commit.\n\t%s' % data[0]
			return False
	except Exception, error:
		print '\n**Error during commit. \n\tScript: %s\n\tError: %s ' % (script, error)
		return False


def check_file_exists(file_path):
	"""Check if file exists and quit on failure."""
	if file_path is not None:
		if not os.path.exists(file_path):
			print '\nError:\File %s does not exist. Exiting...' % file_path
			sys.exit(1)


def delete_file(f):
	"""Deletes a file from the filesystem."""

	try:
		if type(f) is not str:
			f.close()
			f = f.name
		if os.path.exists(f):
			os.remove(f)
		return True

	except Exception, error:
		print('Could not delete file %s.' % f)
		print('Exception: %s' % error)
		return False


def copy_file(orig, dest, delete=False):
	"""Copy file (including wildcard)."""
	for f in glob(orig):
		copyfile(f, dest)
		if delete:
			delete_file(f)


def read_file(filename, skip_lines=0):
	"""Read file and return the full output. `skip_lines` will allow headers (and other content) to be ignored."""
	output = ''
	with open(filename, 'r') as f:
		f.seek(0)
		for i in range(skip_lines):
			next(f)

		for line in f:
			output += line

		f.close()
	return output


def source(script, service=None):
	"""
	Update environment variables to allow execution of 11g BI commands.
	Accepts a path to the `bi-init` shell or Windows command file.
	Optionally accepts a `service` argument of "BI_Server" or "Presentation_Server" when an application needs to be
	specified.
	"""
	try:
		# Based on http://pythonwise.blogspot.fr/2010/04/sourcing-shell-script.html
		if platform.system() == 'Linux':
			pipe = Popen(". %s; env" % script, stdout=PIPE, shell=True)
		else:
			# On a OBIEE-server install, bi-init.cmd will open a command window unless we pass in a dummy command for it.
			# bi-init.cmd (as installed with OBIEE server) != bi_init.bat (as installed with OBIEE admin tools).

			application = 'coreapplication'
			if not CLIENT_ONLY:
				# On OBIEE servers, need to specify the mode to run bi-init.cmd depending on the tool
				# NB if you run these on bi-init.bat (client tools) then some stuff (eg patchrpd) works but others (eg AdminTool)
				if service == 'BI_Server':
					application += '_obis1'
				elif service == 'Presentation_Server':
					application += '_obips1'

			command = '%s %s rem & set' % (script, application)

			pipe = Popen(command, stdout=PIPE, shell=True)
		data = pipe.communicate()[0]
		env = dict(line.split("=", 1) for line in data.splitlines())
		os.environ.update(env)
		return True
	except Exception, error:
		print '\n\nError in source() routine\nException caught: %s ' % error
		print '\nExiting.'
		return False


def bi_command(command, server=False):
	"""
	Returns a valid path to the OBIEE command irrespective of platform and OBIEE version.
	Optionally can set `server` to True, which will use the server installation of the BI tools when both a server and
	client installation are present on the machine.
	"""

	if OBIEE_VERSION == '12':
		if server:  # Force it to use the command on the server when they're both present
			executable = os.path.join(OBIEE_HOME, 'user_projects', 'domains', 'bi', 'bitools', 'bin', command)
		else:
			executable = os.path.join(OBIEE_CLIENT, 'bi', 'bitools', 'bin', command)
		if platform.system() == 'Linux':
			executable += '.sh'
		else:
			executable += '.cmd'
	else:
		if not source(BIINIT_PATH, 'BI_Server'):
			print '\n**Failed to set BI Environment (bi-init). Aborting.'
			return False
		executable = command
	return executable


def create_patch(orig_rpd, orig_pass, curr_rpd, curr_pass, patch_file):
	"""Create XML patch from RPD comparison using OBIEE's `compareRPD` method."""

	print '\nCreating patch...\n'
	compare_log = os.path.join(CURRENT_DIR, 'compareRPD.log')
	log = open(compare_log, 'w')
	script = [bi_command('comparerpd'), '-C', curr_rpd, '-p', curr_pass, '-G', orig_rpd, '-W', orig_pass, '-D', patch_file]
	p = Popen(script, stdout=log, stderr=STDOUT)
	p.wait()

	if os.path.exists(patch_file):
		print '\tPatch created successfully.'
		delete_file(log)
		return True
	else:
		print '\n\tFailed to create patch. See %s for details.\n'\
			  % os.path.abspath(compare_log)
		return False


def admin_tool():
	"""Returns the path to the OBIEE admin executable irrespective of OBIEE 11 or 12."""

	if OBIEE_VERSION == '12':
		if platform.system() == 'Linux':
			executable = os.path.join(OBIEE_CLIENT, 'bi', 'bitools', 'bin', 'admintool.sh')
		else:
			executable = os.path.join(OBIEE_CLIENT, 'bi', 'bitools', 'bin', 'admintool.cmd')
	else:
		if not source(BIINIT_PATH, 'BI_Server'):
			print '\n**Failed to set BI Environment (bi-init). Aborting.'
			return False
		executable = 'admintool.exe'
	return executable


def open_rpd(rpd, password, prompt=True):
	"""Programatically pens an RPD using the Admin Tool."""

	with open('openRPD.txt', 'w') as f:
		f.write('OpenOffline %s %s' % (rpd, password))
		f.close()

	if prompt:
		raw_input('\nWill open RPD using the Admin Tool. \n\nPress Enter key to continue.'
				  '\n\nYou must close the AdminTool after completing the merge manually in order for this'
				  ' script to continue.\n\n')

	call([admin_tool(), '/Command', 'openRPD.txt'])
	delete_file('openRPD.txt')
	return True


def patch_rpd(mod_rpd, mod_pass, orig_rpd, orig_pass, patch_file, out_rpd, out_pass, patch_pass, curr_rpd=False,
			  curr_pass=False, auto_open=False, delete_patch=False):
	"""
	Patches RPD with an XML patch. If conflicts arise, the RPD is opened in the Admin Tool, prompting the user to complete
	the merge manually.
	Current RPD and Password are not mandatory. If not specified, there must NOT be conflicts.
	"""
	print '\nPatching RPD...\n'
	patch_log = os.path.join(CURRENT_DIR, 'patch_rpd.log')
	log = open(patch_log, 'w')

	# Ref: OBIEE 11g Administration Tool: Patch Repository Merge Not Working (Doc ID 1999105.1)
	# -A flag tells patchrpd to skip subset patching and apply patch using input rpds
	script = [bi_command('patchrpd'), '-A', '-C', mod_rpd, '-p', mod_pass, '-G', orig_rpd, '-Q', orig_pass, '-I',
			  patch_file, '-S', patch_pass, '-O', out_rpd]

	p = Popen(script, stdout=log, stderr=STDOUT)
	p.wait()

	if delete_patch:
		delete_file(patch_file)

	if os.path.exists(out_rpd):
		print '\tRPD patched successfully.'
		if auto_open:
			open_rpd(out_rpd, out_pass, False)
		return True
	else:
		print '\tFailed to patch RPD. See %s for details.' % patch_log
		log_contents = read_file(patch_log)
		if re.search('Conflicts are found.', log_contents):
			print '\n\tConflicts detected. Can resolve manually using the Admin Tool.'
			if manual_merge(orig_rpd, mod_rpd, curr_rpd, curr_pass, out_rpd):
				return True
			else:
				return False
		else:
			return False


def manual_merge(orig_rpd, mod_rpd, curr_rpd, curr_pass, out_rpd):
	"""Prompts for a manual merge using the Admin Tool after detecting conflicts whilst attempting to automatically
	patch.
	"""

	if os.path.basename(orig_rpd) == 'original.rpd':
		orig_copy = os.path.join(os.path.dirname(orig_rpd), 'original1.rpd')
	else:
		orig_copy = os.path.join(os.path.dirname(orig_rpd), 'original.rpd')

	if os.path.basename(mod_rpd) == 'modified.rpd':
		mod_copy = os.path.join(os.path.dirname(mod_rpd), 'modified1.rpd')
	else:
		mod_copy = os.path.join(os.path.dirname(mod_rpd), 'modified.rpd')

	if os.path.basename(curr_rpd) == 'current.rpd':
		curr_copy = os.path.join(os.path.dirname(curr_rpd), 'current1.rpd')
	else:
		curr_copy = os.path.join(os.path.dirname(curr_rpd), 'current.rpd')

	print '\n\tOriginal RPD:\t%s (%s)' % (orig_rpd, os.path.basename(orig_copy))
	print '\tCurrent RPD:\t%s (Opened)' % curr_rpd
	print '\tModified RPD:\t%s (%s)' % (mod_rpd, os.path.basename(mod_copy))
	print '\nPerform a full repository merge using the Admin Tool and keep the output name as the default or %s' % out_rpd

	copyfile(curr_rpd, curr_copy)
	copyfile(orig_rpd, orig_copy)
	copyfile(mod_rpd,  mod_copy)

	open_rpd(curr_copy, curr_pass)

	output_file = os.path.basename(os.path.splitext(curr_copy)[0])
	output_file += '(1).rpd'
	output_file = os.path.join(os.path.dirname(curr_rpd), output_file)

	if not os.path.exists(out_rpd):
		if os.path.exists(output_file):
			copyfile(output_file, out_rpd)
			delete_file(output_file)
			delete_file(orig_copy)
			delete_file(mod_copy)
			delete_file(curr_copy)
			return True
		else:
			print '\nError: Output RPD not found. Looking for %s or %s.' % (out_rpd, output_file)
			return False
	return True


def cleanup_rpd_files(directory):
	"""Remove temporary RPD files (from a patch merge)."""

	for f in glob(os.path.join(directory, '*_equalized.rpd')):
		delete_file(f)
	for f in glob(os.path.join(directory, '*_patched.rpd')):
		delete_file(f)
	for f in glob(os.path.join(directory, '*.merge_log.csv')):
		delete_file(f)


def do_three_way_merge(orig_rpd, curr_rpd, modi_rpd, out_rpd, rpd_pass, tidy):
	if orig_rpd == out_rpd or curr_rpd == out_rpd or modi_rpd == out_rpd:
		print '\nOutput RPD filename cannot be the same as any of the input RPD filename. Exiting.'
		return False

	check_file_exists(orig_rpd)
	check_file_exists(curr_rpd)
	check_file_exists(modi_rpd)

	if not delete_file(out_rpd):
		print '\n** Could not delete output RPD. Is it open in the Administration Tool or write-protected?'
		print 'Exiting'
		return False

	if not create_patch(orig_rpd, rpd_pass, curr_rpd, rpd_pass, PATCH_FILE):
		print '\n**create_patch failed. Aborting.'
		return False

	if tidy:
		delete_patch = True
	else:
		delete_patch = False

	if patch_rpd(modi_rpd, rpd_pass, orig_rpd, rpd_pass, PATCH_FILE,  out_rpd, rpd_pass, rpd_pass, curr_rpd, rpd_pass,
				 AUTO_OPEN, delete_patch):
		if TIDY:
			cleanup_rpd_files(os.path.dirname(curr_rpd))

			delete_file(curr_rpd)
			delete_file(modi_rpd)
			delete_file(orig_rpd)

		print '\nRPD Merge complete.\n-------------------\n\n'
		return True

	else:
		print '\n\tRPD Merge, both automatic and manual, **FAILED**'
		return False


def reintegrate(src_url, target_url, rpd_pass, commit_message=None):
	action = 'Reintegrate Merge from %s to %s' % (src_url, target_url)
	if ACTION == 'reintegrate':
		print action
	if commit_message is None:
		commit_message = action

	if rpd_pass is None:
		print 'RPD password must be supplied. Aborting'
		return False

	wc = tempfile.mkdtemp(prefix='rm_rpdmerge')

	if not svn_checkout(url=target_url, wc=wc, force=True):
		print '\n**Failed to checkout %s to %s' % (target_url, wc)
		return False

	merge_output = svn_merge(srcurl=src_url, target_wc=wc, re_integrate=True, accept='postpone')

	if merge_output:
		if 'Text conflicts' in merge_output:
			print '\n** Conflicts detected'
			lines = merge_output.split('\n')
			for line in lines:
				pattern = re.compile('^C    ')
				m = pattern.match(line)
				if m:
					# This matches fine on Unix paths / but not Windows \
					# Should be able to use just this single expression in the
					# above match too, but can't.
					pattern = re.compile('^C\s*([^\s]*\.rpd)$')
					m = pattern.match(line)
					if m:
						conflicting_rpd_file = m.group(1)
					else:
						conflicting_rpd_file = line.replace('C    ', '')

					conflicting_rpd_file = conflicting_rpd_file.replace('\r', '')
					glob_path = ('%s*' % conflicting_rpd_file)

					merge_candidates = glob(glob_path)

					modified_rpd = None
					original_rpd = None
					current_rpd = conflicting_rpd_file
					for candidate in merge_candidates:
						if re.search('.*merge-left.*', candidate):
							original_rpd = candidate
						if re.search('.*merge-right.*', candidate):
							modified_rpd = candidate
					if original_rpd is None or current_rpd is None:
						print '\n**Failed to identify original/current merge candidates! List of contenders : \n%s' \
							  % merge_candidates
						return False

					if REVERSE_MERGE_CANDIDATES:
						print '** Reversing the current/modified merge candidates **'
						current_rpd_tmp = current_rpd
						current_rpd = modified_rpd
						modified_rpd = current_rpd_tmp

					output_rpd = '%s.merged.rpd' % modified_rpd

					if do_three_way_merge(orig_rpd=original_rpd, modi_rpd=modified_rpd, curr_rpd=current_rpd,
										  out_rpd=output_rpd, rpd_pass=rpd_pass, tidy=True):
						print 'Three way merge successful!'
						try:
							delete_file(conflicting_rpd_file)
							delete_file(original_rpd)
							delete_file(modified_rpd)
							os.rename(output_rpd, conflicting_rpd_file)
						except Exception as error:
							print '\n**Failed to rename %s to %s\n\t%s' % (output_rpd, conflicting_rpd_file, error)
							return False
					else:
						print 'Three way merge failed'
						return False

		if 'Tree conflicts' in merge_output:
			print '\n**Tree conflicts detected in output. This is bad, because we can\'t fix that for you automagically.' \
				  '\nIt can be caused by created the same folder in parallel branches and will occur when you try to' \
				  ' reintegrate those branches. The working copy (%s) is now in a conflicted state, and you should fix ' \
				  'and commit it manually.\n\n**Aborting.' % wc
			call(['explorer.exe', wc])

			return False

		if svn_commit(wc, commit_message):
			print 'Successfully commited WC. All good.'
			return True
		else:
			print '\n**Commit failed. Working copy %s is probably in a mess and should be cleaned up.' % wc
			return False

	else:
		print '\n**Merge failed. Aborting.'
		return False


def start_release(release_name):
	release_branch_name = '%s-%s' % (SVN_RELEASE_BRANCH_ROOT, release_name)
	source_url = '%s/%s' % (SVN_BASE_URL, SVN_DEVELOP)
	dest_url = '%s/%s' % (SVN_BASE_URL, release_branch_name)
	if COMMIT_MESSAGE is None:
		commit_message = '%s: Start Release     [via merge_rpd.py]' % release_name
	else:
		commit_message = COMMIT_MESSAGE

	if svn_copy(source_url,dest_url,commit_message):
		print '\nSuccessfully created new branch %s' % release_branch_name
		return True
	else:
		print '\n**Failed to create new branch %s' % release_branch_name
		return False


def start_feature(feature_name):
	feature_branch_name = '%s-%s' % (SVN_DEV_BRANCH_ROOT, feature_name)
	source_url = '%s/%s' % (SVN_BASE_URL, SVN_DEVELOP)
	dest_url = '%s/%s' % (SVN_BASE_URL, feature_branch_name)
	if COMMIT_MESSAGE is None:
		commit_message = '%s: Start Feature     [via merge_rpd.py]' % feature_name
	else:
		commit_message = COMMIT_MESSAGE

	if svn_copy(source_url, dest_url, commit_message):
		print '\nSuccessfully created new branch %s' % feature_branch_name
		return True
	else:
		print '\n**Failed to create new branch %s' % feature_branch_name
		return False


def start_release_hotfix(release_name, hotfix_name):
	release_hotfix_branch_name = '%s-%s-%s' % (SVN_RELEASE_HF_BRANCH_ROOT, release_name, hotfix_name)
	release_branch_name = '%s-%s' % (SVN_RELEASE_BRANCH_ROOT, release_name)
	source_url = '%s/%s' % (SVN_BASE_URL, release_branch_name)
	dest_url = '%s/%s' % (SVN_BASE_URL, release_hotfix_branch_name)
	if COMMIT_MESSAGE is None:
		commit_message = '%s: Start Release %s Hotfix    [via merge_rpd.py]' % (hotfix_name, release_name)
	else:
		commit_message = COMMIT_MESSAGE

	if svn_copy(source_url, dest_url, commit_message):
		print '\nSuccessfully created new branch %s' % release_hotfix_branch_name
		return True
	else:
		print '\n**Failed to create new branch %s' % release_hotfix_branch_name
		return False


def start_hotfix(hotfix_name):
	hotfix_branch_name = '%s-%s' % (SVN_HF_BRANCH_ROOT, hotfix_name)
	source_url = '%s/%s' % (SVN_BASE_URL, SVN_TRUNK)
	dest_url = '%s/%s' % (SVN_BASE_URL, hotfix_branch_name)
	if COMMIT_MESSAGE is None:
		commit_message = '%s: Start Hotfix    [via merge_rpd.py]' % hotfix_name
	else:
		commit_message = COMMIT_MESSAGE

	if svn_copy(source_url, dest_url):
		print '\nSuccessfully created new branch %s' % hotfix_branch_name
		return True
	else:
		print '\n**Failed to create new branch %s' % hotfix_branch_name
		return False


def finish_feature(feature_name, delete_feature=False):
	# Automatic feature branch deletion not implemented yet
	feature_branch_name = '%s-%s' % (SVN_DEV_BRANCH_ROOT, feature_name)
	dest_url = '%s/%s' % (SVN_BASE_URL, SVN_DEVELOP)
	source_url = '%s/%s' % (SVN_BASE_URL, feature_branch_name)
	if COMMIT_MESSAGE is None:
		commit_message = '%s: Finish Feature    [via merge_rpd.py]' % feature_name
	else:
		commit_message = COMMIT_MESSAGE

	if reintegrate(src_url=source_url, target_url=dest_url, rpd_pass=RPD_PASS, commit_message=commit_message):
		print '\nSuccessfully reintegrated feature %s back into develop\n\n**It would be good practice to now delete ' \
			  'the feature branch**' % feature_branch_name
		return True
	else:
		print '\nFailed to reintegrate feature %s back into develop' % feature_branch_name
		return False


def finish_release(release_name, delete_feature=False):
	# Automatic feature branch deletion not implemented yet
	feature_branch_name = '%s-%s' % (SVN_RELEASE_BRANCH_ROOT, release_name)
	dest_url = '%s/%s' % (SVN_BASE_URL, SVN_TRUNK)
	source_url = '%s/%s' % (SVN_BASE_URL, feature_branch_name)
	if COMMIT_MESSAGE is None:
		commit_message = '%s: Finish Release    [via merge_rpd.py]' % (release_name)
	else:
		commit_message = COMMIT_MESSAGE

	if reintegrate(src_url=source_url, target_url=dest_url, rpd_pass=RPD_PASS, commit_message=commit_message):
		print '\nSuccessfully reintegrated release %s into trunk\n\n**It would be good practice to now delete the ' \
			  'release branch**' % feature_branch_name
		return True
	else:
		print '\nFailed to reintegrate release %s into trunk' % feature_branch_name
		return False


def finish_release_hotfix(release_name, hotfix_name, delete_feature=False):
	# Automatic feature branch deletion not implemented yet
	release_hotfix_branch_name = '%s-%s-%s' % (SVN_RELEASE_HF_BRANCH_ROOT, release_name, hotfix_name)
	release_branch_name = '%s-%s' % (SVN_RELEASE_BRANCH_ROOT, release_name)
	dest_url = '%s/%s' % (SVN_BASE_URL, release_branch_name)
	source_url = '%s/%s' % (SVN_BASE_URL, release_hotfix_branch_name)
	if COMMIT_MESSAGE is None:
		commit_message = '%s: Finish Release %s Hotfix    [via merge_rpd.py]' % (hotfix_name,release_name)
	else:
		commit_message = COMMIT_MESSAGE

	if reintegrate(src_url=source_url, target_url=dest_url, rpd_pass=RPD_PASS, commit_message=commit_message):
		print '\n(1 of 2) Successfully reintegrated hotfix release %s into release branch %s\n\n' % (release_hotfix_branch_name,release_branch_name)
		dest_url = '%s/%s' % (SVN_BASE_URL, SVN_DEVELOP)
		if reintegrate(src_url=source_url, target_url=dest_url, rpd_pass=RPD_PASS, commit_message=commit_message):
			print '\n(2 of 2) Successfully reintegrated hotfix release %s into develop branch\n\n**It would be good ' \
				  'practice to now delete the release hotfix branch**' % release_hotfix_branch_name
			return True
		else:
			print '\n**Failed to reintegrate hotfix release %s into develop' % release_hotfix_branch_name

	else:
		print '\nFailed to reintegrate hotfix release %s into release branch%s' % (release_hotfix_branch_name,
																				   release_branch_name)
		return False


def finish_hotfix(hotfix_name, delete_feature=False):
	# Automatic feature branch deletion not implemented yet
	hotfix_branch_name = '%s-%s' % (SVN_HF_BRANCH_ROOT, hotfix_name)
	dest_url = '%s/%s' % (SVN_BASE_URL, SVN_TRUNK)
	source_url = '%s/%s' % (SVN_BASE_URL, hotfix_branch_name)
	if COMMIT_MESSAGE is None:
		commit_message = '%s: Finish Hotfix    [via merge_rpd.py]' % (hotfix_name)
	else:
		commit_message = COMMIT_MESSAGE

	if reintegrate(src_url=source_url, target_url=dest_url, rpd_pass=RPD_PASS, commit_message=commit_message):
		print '\n(1 of 2) Successfully reintegrated hotfix %s into trunk\n\n' % hotfix_branch_name
		dest_url = '%s/%s' % (SVN_BASE_URL, SVN_DEVELOP)
		if reintegrate(src_url=source_url, target_url=dest_url, rpd_pass=RPD_PASS, commit_message=commit_message):
			print '\n(2 of 2) Successfully reintegrated hotfix %s into develop branch\n\n**It would be good practice to ' \
				  'now delete the hotfix branch**' % hotfix_branch_name
			return True
		else:
			print '\n**Failed to reintegrate hotfix %s into develop' % hotfix_branch_name

	else:
		print '\nFailed to reintegrate hotfix %s into trunk ' % hotfix_branch_name
		return False


def refresh_feature(feature_name, delete_feature = False):
	feature_branch_name = '%s-%s' % (SVN_DEV_BRANCH_ROOT, feature_name)
	source_url = '%s/%s' % (SVN_BASE_URL, SVN_DEVELOP)
	dest_url = '%s/%s' % (SVN_BASE_URL, feature_branch_name)
	if COMMIT_MESSAGE is None:
		commit_message = '%s: Refresh Feature from develop    [via merge_rpd.py]' % (feature_name)
	else:
		commit_message = COMMIT_MESSAGE

	if reintegrate(src_url=source_url, target_url=dest_url, rpd_pass=RPD_PASS, commit_message=commit_message):
		print '\nSuccessfully refreshed feature %s from develop' % feature_branch_name
		return True
	else:
		print '\nFailed to refresh feature %s from develop' % feature_branch_name
		return False


def main():
	if ACTION == 'standaloneRPDMerge':
		do_three_way_merge(ORIG_RPD, CURR_RPD, MODI_RPD, OUT_RPD, RPD_PASS, TIDY)
	elif ACTION == 'reintegrate':
		reintegrate(src_url=SOURCE_URL, target_url=TARGET_URL, rpd_pass=RPD_PASS, commit_message=COMMIT_MESSAGE)
	elif ACTION == 'startFeature':
		start_feature(FEATURE_NAME)
	elif ACTION == 'startReleaseHotfix':
		start_release_hotfix(RELEASE_NAME, HOTFIX_NAME)
	elif ACTION == 'startRelease':
		start_release(RELEASE_NAME)
	elif ACTION == 'startHotfix':
		start_hotfix(HOTFIX_NAME)
	elif ACTION == 'finishFeature':
		finish_feature(FEATURE_NAME)
	elif ACTION == 'finishRelease':
		finish_release(RELEASE_NAME)
	elif ACTION == 'finishReleaseHotfix':
		finish_release_hotfix(RELEASE_NAME, HOTFIX_NAME)
	elif ACTION == 'finishHotfix':
		finish_hotfix(HOTFIX_NAME)
	elif ACTION == 'refreshFeature':
		refresh_feature(FEATURE_NAME)

if __name__ == "__main__":
	main()
