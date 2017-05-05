#! /usr/bin/env python
"""Script to manage concurrent RPD development using Git in a Gitflow methodology.

Rittman Mead

Prerequisites:
	Python 2.7
"""

import os
import re
import sys
import platform
from glob import glob
from shutil import copyfile
from argparse import ArgumentParser
from ConfigParser import SafeConfigParser
from subprocess import Popen, PIPE, STDOUT, call

SCRIPT_DIR = os.path.abspath(os.path.dirname(sys.argv[0]))
CURRENT_DIR = os.getcwd()


try:
	os.chdir(SCRIPT_DIR)  # Change to script directory

	# ArgumentParser to parse arguments and options
	arg_parser = ArgumentParser(description="Rittman Mead RPD Git Merge Script \n(MP/RM Jul 2016)")
	arg_parser.add_argument('action', choices=['startFeature', 'finishFeature', 'refreshFeature', 'startRelease',
											   'finishRelease', 'startHotfix', 'finishHotfix'], help='Gitflow action.')
	arg_parser.add_argument('name', help='Name of a feature, release or hotfix depending on the action chosen.')
	arg_parser.add_argument('-p', '--push', action="store_true", default=False, help='Push directly to origin.')
	arg_parser.add_argument('-a', '--autoOpen', action="store_true", default=False,
						help='Automatically opens new RPD after merge.')
	arg_parser.add_argument('-t', '--tag', action="store", help='Specify tag annotation if finishing a release.')
	arg_parser.add_argument('-c', '--config', default='config.ini', help='Config file to be used. Default: "config.ini"')
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

	# Initiliases bi-init and runcat command variables
	if platform.system() == 'Linux':
		# This won't work for multi-instance BI Homes (instance2 etc)
		BIINIT_PATH = '%s/instances/instance1/bifoundation/OracleBIApplication/coreapplication/setup/bi-init.sh' % OBIEE_HOME

	else:
		if CLIENT_ONLY:
			BIINIT_PATH = '%s\\oraclebi\\orahome\\bifoundation\\server\\bin\\bi_init.bat' % OBIEE_HOME
		else:
			# This won't work for multi-instance BI Homes (instance2 etc)
			BIINIT_PATH = '%s\\instances\\instance1\\bifoundation\\OracleBIApplication\\coreapplication\\setup\\bi-init.cmd'\
						  % OBIEE_HOME
		BIINIT_PATH = BIINIT_PATH.replace(' ', '^ ')

	GIT_EXE = conf_parser.get('Git', 'GIT_EXE')
	GIT_REPO = conf_parser.get('Git', 'GIT_REPO')
	GIT_RPD = conf_parser.get('Git', 'GIT_RPD')
	GIT_REMOTE = conf_parser.get('Git', 'GIT_REMOTE')
	GIT_DEVELOP = conf_parser.get('Git', 'GIT_DEVELOP')
	GIT_MASTER = conf_parser.get('Git', 'GIT_MASTER')
	FEATURE_PREFIX = conf_parser.get('Git', 'FEATURE_PREFIX')
	HOTFIX_PREFIX = conf_parser.get('Git', 'HOTFIX_PREFIX')
	RELEASE_PREFIX = conf_parser.get('Git', 'RELEASE_PREFIX')

	ACTION = args.action
	NAME = args.name
	PUSH = args.push
	TAG = args.tag
	AUTO_OPEN = args.autoOpen

	if (ACTION == 'startFeature' or ACTION == 'finishFeature' or ACTION == 'refreshFeature') and NAME is None:
		arg_parser.print_help()
		print '\n\tError: Name (-n, --name) must be specified.'
		sys.exit(1)

except Exception, err:
	print '\n\nException caught:\n\n%s ' % err
	print '\n\n\tFailed to get command line arguments. Exiting.'
	sys.exit(1)


def cmd(command):
	"""
	Executes a Git command and reports an error if one is detected.

	E.g.

	cmd(['pull'])
	"""

	command = [GIT_EXE, '-C', GIT_REPO] + command
	output = Popen(command, stdout=PIPE, stderr=PIPE).communicate()
	if output[1]:
		print(output[1])
	return output


def checkout(branch_name):
	"""Checks out a Git branch."""

	print('Checking out %s...' % branch_name)
	cmd(['checkout', branch_name])


def pull():
	"""Pulls latest changes from the tracked remote Git repository."""
	cmd(['fetch'])
	out = cmd(['pull'])
	return out


def branch(branch_name, base):
	"""Creates a new branch from an existing branch (`base`)."""
	checkout(base)
	pull()
	out = cmd(['checkout', '-b', branch_name, base])
	return out


def delete_branch(branch_name):
	"""Delete a Git branch."""
	out = cmd(['branch', '-d', branch_name])
	return out


def merge(trunk, branch_name, no_ff=False):
	"""Merges a Git branch to a trunk."""
	checkout(trunk)
	out = pull()
	if out[1]:
		if re.search('no tracking information', out[1]):  # Check if pull failed because there is no remote
			if trunk in [GIT_DEVELOP, GIT_MASTER]:  # If trunk is not one of the main trunks we should exit with failure
				return out

	print('Merging %s into %s...' % (branch_name, trunk))
	if no_ff:
		out = cmd(['merge', '--no-ff', branch_name])
	else:
		out = cmd(['merge', branch_name])
	return out


def push(remote, branch_name):
	"""Pushes a branch to a remote repository."""
	print('Pushing %s to %s...' % (branch_name, remote))
	out = cmd(['push', remote, branch_name])
	return out


def commit_all(msg):
	"""Commits all changes."""
	out = cmd(['commit', '-a', '-m', msg])
	return out


def tag(tag_name, branch_name, msg=""):
	"""Tag commit on a specific branch, optionally using a message."""
	print('Tagging %s with %s...' % (branch_name, tag_name))
	checkout(branch_name)
	cmd(['tag', '-a', tag_name, '-m', msg])


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


def git_bi_merge(trunk, branch_name):
	"""Merges an RPD branch into a different trunk branch, calling the Admin Tool to resolve OBI conflicts."""
	merge_out = merge(trunk, branch_name)
	if merge_out[1]:  # Indicates merge failure/conflict
		# Get candidates for 3-way merge
		cmd(['checkout-index', '--stage=all', '--temp', GIT_RPD])

		# Rename by wildcards
		orig_rpd = os.path.join(GIT_REPO, 'a.rpd')
		mod_rpd = os.path.join(GIT_REPO, 'b.rpd')
		curr_rpd = os.path.join(GIT_REPO, 'c.rpd')
		out_rpd = os.path.join(GIT_REPO, GIT_RPD)

		copy_file(os.path.join(GIT_REPO, '.merge_file_a*'), orig_rpd, True)
		copy_file(os.path.join(GIT_REPO, '.merge_file_b*'), mod_rpd, True)
		copy_file(os.path.join(GIT_REPO, '.merge_file_c*'), curr_rpd, True)

		bi_merge_out = three_way_merge(orig_rpd, curr_rpd, mod_rpd, out_rpd, RPD_PW, AUTO_OPEN, True)
		if bi_merge_out:
			commit_out = commit_all('OBI Merged %s into %s.' % (branch_name, trunk))
			if commit_out:
				return True
			else:
				print('Error: Failed to commit the RPD, please complete manually or discard changes on the branch.')
				return False
		else:
			print('Error: Failed to merge %s to the %s branch. Please complete the merge manually,'
				  ' or discard all changes on the branch.' % (branch_name, trunk))
			return False
	else:
		return True


def merge_to_both(branch_name, tag_name=None):
	"""Merges to develop and master trunks"""
	master_response = git_bi_merge(GIT_MASTER, branch_name)
	if master_response:
		merge_success(GIT_MASTER, branch_name)
		if tag_name:
			tag(tag_name, GIT_MASTER)

	develop_response = git_bi_merge(GIT_DEVELOP, branch_name)
	if develop_response:
		merge_success(GIT_DEVELOP, branch_name)

	if master_response and develop_response:
		delete_branch(branch_name)


def check_file_exists(file_path):
	"""Check if file exists and quit on failure."""
	if file_path is not None:
		if not os.path.exists(file_path):
			print '\nError:\File %s does not exist. Exiting...' % file_path
			sys.exit(1)


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

	# OBIEE 11g vs 12g branch
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


def three_way_merge(orig_rpd, curr_rpd, mod_rpd, out_rpd, rpd_pass=False, auto_open=False, tidy=False):
	"""
	Performs a full three way RPD merge by first creating a patch using `compareRPD` between the original and current RPDs.
	This patch is then applied to the modified RPD using the original as a baseline.
	If merge conflicts are detected, the RPD is opened in the Admin Tool and the user is prompted to resolve the merge
	manually.
	Requires original, current and modified RPDs as well as specified output.
	If `rpd_pass` is unset, the `rm_sys.RPD_PW` global variable (set in [OBIEE]) will be used.
	Setting `auto_open` to True will cause hte program to open the output RPD in the Admin Tool after the merge, which can
	be useful for manual checking.
	Setting `tidy` to True will remove all working RPD files, **including** the original, modified and current RPDs.
	This leaves **only** the output RPD.
	"""

	patch_file = os.path.join(CURRENT_DIR, 'patch.xml')

	if not rpd_pass:
		rpd_pass = RPD_PW

	if orig_rpd == out_rpd or curr_rpd == out_rpd or mod_rpd == out_rpd:
		print '\nOutput RPD filename cannot be the same as any of the input RPD filename. Exiting.'
		return False

	# Check RPD files exist
	check_file_exists(orig_rpd)
	check_file_exists(curr_rpd)
	check_file_exists(mod_rpd)

	if not delete_file(out_rpd):
		print '\n** Could not delete output RPD. Is it open in the Administration Tool or write-protected?'
		print 'Exiting'
		return False

	if not create_patch(orig_rpd, rpd_pass, curr_rpd, rpd_pass, patch_file):
		print '\n**create_patch failed. Aborting.'
		return False

	if patch_rpd(mod_rpd, rpd_pass, orig_rpd, rpd_pass, patch_file, out_rpd, rpd_pass, rpd_pass, curr_rpd, rpd_pass,
				 auto_open, tidy):
		if tidy:
			cleanup_rpd_files(os.path.dirname(curr_rpd))

			delete_file(curr_rpd)
			delete_file(mod_rpd)
			delete_file(orig_rpd)

		print '\nRPD Merge complete.\n\n'
		return True
	else:
		print '\n\tError: RPD Merge, both automatic and manual failed, '
		return False


def merge_success(trunk, branch_name, delete=False):
	if delete:
		delete_branch(branch_name)  # Delete feature branch if merge is successful
	if PUSH:
		push(GIT_REMOTE, trunk)
	print('Successfully merged %s to the %s branch.' % (branch_name, trunk))


def start_feature(feature):
	feature_name = FEATURE_PREFIX + feature
	branch(feature_name, GIT_DEVELOP)


def finish_feature(feature):
	feature_name = FEATURE_PREFIX + feature
	response = git_bi_merge(GIT_DEVELOP, feature_name)
	if response:
		merge_success(GIT_DEVELOP, feature_name, True)


def refresh_feature(feature):
	feature_name = FEATURE_PREFIX + feature
	response = git_bi_merge(feature_name, GIT_DEVELOP)
	if response:
		print('\nRefreshed %s successfully from %s.' % (feature, GIT_DEVELOP))


def start_release(release):
	release_name = RELEASE_PREFIX + release
	branch(release_name, GIT_DEVELOP)


def bugfix(release):
	release_name = RELEASE_PREFIX + release
	response = git_bi_merge(GIT_DEVELOP, release_name)
	if response:
		merge_success(GIT_DEVELOP, release_name)


def finish_release(release, tag_name):
	release_name = RELEASE_PREFIX + release
	merge_to_both(release_name, tag_name)


def start_hotfix(hotfix):
	hotfix_name = HOTFIX_PREFIX + hotfix
	branch(hotfix_name, GIT_MASTER)


def finish_hotfix(hotfix, tag_name):
	hotfix_name = HOTFIX_PREFIX + hotfix
	merge_to_both(hotfix_name, tag_name)


def main():
	if ACTION == 'startFeature':
		start_feature(NAME)
	elif ACTION == 'finishFeature':
		finish_feature(NAME)
	elif ACTION == 'refreshFeature':
		refresh_feature(NAME)
	elif ACTION == 'startRelease':
		start_release(NAME)
	elif ACTION == 'finishRelease':
		if TAG is None:
			finish_release(NAME, NAME)
		else:
			finish_release(NAME, TAG)
	elif ACTION == 'startHotfix':
		start_hotfix(NAME)
	elif ACTION == 'finishHotfix':
		if TAG is None:
			finish_hotfix(NAME, NAME)
		else:
			finish_hotfix(NAME, TAG)
	elif ACTION == 'bugfix':
		bugfix(NAME)

if __name__ == "__main__":
	main()
