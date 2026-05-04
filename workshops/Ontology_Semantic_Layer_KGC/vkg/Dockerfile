FROM public.ecr.aws/amazoncorretto/amazoncorretto:21-al2023

RUN dnf install -y unzip shadow-utils && dnf clean all
RUN useradd -m ontopuser

WORKDIR /opt/ontop

# Ontop CLI will be downloaded and extracted during CodeBuild
COPY ontop-cli/ ./
COPY input/ /opt/ontop/input/
COPY setup-h2.sh /opt/ontop/setup-h2.sh

RUN chmod +x ontop setup-h2.sh && mkdir -p db && chown -R ontopuser:ontopuser /opt/ontop

USER ontopuser
EXPOSE 8080
ENTRYPOINT ["/bin/bash", "/opt/ontop/setup-h2.sh"]
CMD ["endpoint", \
     "--ontology=/opt/ontop/input/insurance.owl", \
     "--mapping=/opt/ontop/input/insurance.obda", \
     "--properties=/opt/ontop/input/insurance.properties", \
     "--port=8080"]
