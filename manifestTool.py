import ssl, OpenSSL, requests, json, yaml, sys, time, os

# needed to subvert https request failure
from subprocess import call
try:
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except:
    pass

postHeaders = {'content-type': 'application/json'}
getHeaders = {'accept': 'application/json'}
payload = { "format": "repr" }

arguments = sys.argv[1:]
# defaulting to https and 8443 due to telstra running in ssl
serverIp = "https://localhost:8443"
manifestFileName = "/root/manifestTool/manifests/aggregate_plugin_manifest.yml"


while len(arguments):
    if(arguments[0] == '-help'):
        print("\n")
        print("-file: file path to manifest")
        print("Defaults to /root/manifest/manifests/aggregate_plugin_manifest.yml")
        print("Value: file path")
        print("\n")
        print("-http: sets manifest tool to use port 8080")
        print("Defaults to https, port 8443. Use this flag to set to http, port 8080")
        print("Value: flag only")
        print("\n")
        sys.exit(0)
        # print("-server: full url of the server you wish to run against")
        # print("E.G https://192.168.56.105:8443")
    elif(arguments[0] == '-file'):
        manifestFileName = arguments[1]
        arguments = arguments[2:]
    elif(arguments[0] == '-http'):
        serverIp = "http://localhost:8080"
        arguments = arguments[1:]
    # taking out due to paring down of script; script will assume localhost:8443 @ telstra
    # elif(arguments[0] == '-server'):
    #     stringI = str(arguments[1])
    #     if(not stringI[0:4] == "http"):
    #         print("Please pass in the URL of the server you wish to check against")
    #         print("Example: http://localhost:8080")
    #         sys.exit(1)
    #     serverIp = str(arguments[1])
    #     arguments = arguments[2:]
    else:
        print("Flag not recognized, please try again or use the -help flag for usage info")
        sys.exit(1)

with open(manifestFileName, "r") as stream:
    try:
        parsedYml = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        print(exc)
        sys.exit(1)

# get the re endpoint for RE VIP info
# if returns ! 200, throw error and end
# if there are no attached re's, throw error and end. May be better to continue as normal as low chance
# interate through the re vips, adding the urls to primaryRes but removing /re
primaryRes = []
r = requests.get(f'{serverIp}/genesys/diag/health/re', auth=('admin', 'admin'), headers=getHeaders, verify=False)
# if server encounters an error or no RE's are attached, end
if(r.status_code != 200):
    print(r.status_code)
    print("Response to pinging RE endpoint was not 200, please check the status of the Server and try again")
    sys.exit(1)
elif(len(r.json()["attachedReList"]) == 0):
    print("Please check if RE's are attached and try again")
    sys.exit(1)
else:
    for i in r.json()["attachedReList"]:
        primaryRes.append(i["primaryReUrl"][0:-3])

rdDict = {}
# creating a empty dictonary to hold resource driver keys + values
# iterate through all drivers (both RE VIPS), storing name / version as key value pairs
# check if the version is 2.12 or 2.11 or less, then loop through
# note that 9.9.9 denotes a personal build and as of time of writing is ~ 2.12
for i in primaryRes:
    if(i[-1] == '/'):
        i = i[0:-1]
    r = requests.get(f'{i}/re/buildInfo', auth=('admin', 'admin'), headers=getHeaders, verify=False)
    if(r.status_code != 200):
        print(r.status_code)
        print(f'Please check the status of RE {i}')
        sys.exit(1)
        # test if details or plugins exist in r.json() depedning on version #
        # if so, test if drivers or plugins exist below that
        # neither of above, means no drivers? Not sure what that state means
    elif(r.json()["version"].split('.')[1] == '12' or r.json()["version"].split('-')[0] == '9.9.9'):
        if(not "details" in r.json() or not "plugins" in r.json()["details"]):
            print('REs encountered an error retriving list of 2.12 RD values, please reach out to seastreet support')
            sys.exit(1)
        for rd in r.json()["plugins"]["plugin"]:
            rdDict[rd["name"]] = rd["version"]
    elif(r.json()["version"].split('.')[1] == '7'):
        print("ManifestTool is not supported on StratOS version 2.7, exiting")
        sys.exit(127)
    else:
        if(not "details" in r.json() or not "drivers" in r.json()["details"]):
            print('REs encountered an error retriving list of 2.7 + RD values, please reach out to seastreet support')
            sys.exit(1)
        for rd in r.json()["details"]["drivers"]:
            rdDict[rd["name"]] = rd["version"]

for i in parsedYml:
    mavenArtifactId = i["vars"]["maven_artifactId"]
    mavenVersion = i["vars"]["maven_version"]

# if the groupId ends in "package", check against the server
# if the groupId ends in "rd", check against the re buildInfo
# otherwise, probably throw an error

    # split the groupId field by '.' and get the last one
    if(i["vars"]["maven_groupId"].split('.')[-1] == "package"):
        r = requests.get(f'{serverIp}/genesys/package/{mavenArtifactId}?format=repr', auth=('admin', 'admin'), headers=getHeaders, verify=False)
        # does it return a valid response?
        # does it match in both name and version.
        if(r.status_code == 200):
            # version for packages includes major and minor (patch tag) versions
            totalVersion = r.json()[0]["version"] + "." + r.json()[0]["tags"][0].split('=')[-1]
            if(mavenArtifactId == r.json()[0]["name"]):
                if(i["vars"]["maven_version"].split('-')[0] == totalVersion):
                    print("Package \'" + r.json()[0]["name"] + "\' is at version")
                    print("\'" + totalVersion + "\'")
                    print("\n")
                else:
                    print("Package \'" + r.json()[0]["name"] + "\' does not match value found on the server")
                    print("     Manifest Version \'" + i["vars"]["maven_version"].split('-')[0] + "\' : Server Version " + "\'" + totalVersion + "\'")
                    print("\n")
        elif(r.status_code == 404):
                print("Package \'" + i["vars"]["maven_artifactId"] + "\' does not match any known package on the server")
                print("\n")
        else:
            print("Package \'" + i["vars"]["maven_artifactId"] + "\' encountered a server error")
            print("\n")

    elif(i["vars"]["maven_groupId"].split('.')[-1] == "rd"):
        # check if the maven name exists in the RD build info
        # if yes, then check version
        # if no, then return 404
        if(mavenArtifactId in rdDict.keys()):
            # if there is more than one version of the same rd
            # check all the versions for matching with desired version
            # splitting mavenVersion to clean up 1.0.0.1-20210505.xxxx
            if(mavenVersion.split("-")[0] == rdDict[mavenArtifactId]):
                print("Resource Driver \'" + mavenArtifactId + "\' is at version")
                print(mavenVersion)
                print("\n")
            else:
                print("Resource Driver \'" + mavenArtifactId + "\' does not match value found on the server")
                print("     Manifest Version \'" + mavenVersion.split("-")[0] + "\' : Server Version " + "\'" + rdDict[mavenArtifactId] + "\'")
                print("\n")
        else:
            print("Resource Driver \'" + mavenArtifactId + "\' does not match any known RD on the server")
            print("\n")
sys.exit(0)
